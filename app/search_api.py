"""Server-side report search and place suggestions.

The index is cached per process but validated on every request against a cheap
database fingerprint (number and latest time of reports, status changes and passes).
When any replica writes a report or a status change, every replica rebuilds on
its next query, so results never depend on which replica answers.
"""
import threading
import time
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from .auth import SessionGuard
from .repository import PotholeStatus
from .search_index import ReportSearchIndex
from . import schema as s

ACTIVE_STATUSES = [status for status in PotholeStatus.ALL if status not in PotholeStatus.INACTIVE]


class SearchIndexCache:
    MAX_REPORTS = 10_000

    def __init__(self, engine, repo):
        self.engine, self.repo = engine, repo
        self.lock = threading.Lock()
        self.fingerprint = None
        self.index: ReportSearchIndex | None = None
        self.built_at = 0
        self.build_ms = 0.0

    def _fingerprint(self) -> tuple:
        with self.engine.connect() as conn:
            reports = conn.execute(select(func.count(), func.max(s.reports.c.created_at))).one()
            events = conn.execute(select(func.count(), func.max(s.status_events.c.created_at))).one()
            zones = conn.execute(select(func.max(s.zones.c.resolved_at))).scalar_one()
            passes = conn.execute(select(func.count(), func.max(s.pothole_passes.c.created_at))).one()
        # Passes are included because results carry people and pass counts.
        return (*reports, *events, zones, *passes)

    def get(self) -> tuple[ReportSearchIndex, bool]:
        fingerprint = self._fingerprint()
        with self.lock:
            if self.index is not None and fingerprint == self.fingerprint:
                return self.index, False
            started = time.perf_counter()
            # Same visibility as GET /api/reports: active potholes only.
            reports, _ = self.repo.list_reports(self.MAX_REPORTS, 0, statuses=ACTIVE_STATUSES)
            self.index = ReportSearchIndex(reports)
            self.fingerprint, self.built_at = fingerprint, s.Clock.now()
            self.build_ms = round((time.perf_counter() - started) * 1000, 1)
            return self.index, True


def search_cache(request: Request) -> SearchIndexCache:
    state = request.app.state
    if getattr(state, 'search_cache', None) is None:
        state.search_cache = SearchIndexCache(state.engine, state.repo)
    return state.search_cache


class SearchController:
    """GET /api/reports/search and /api/reports/suggest; a session is required."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/reports', dependencies=[Depends(SessionGuard.current)])
        self.router.add_api_route('/search', self.search_reports, methods=['GET'])
        self.router.add_api_route('/suggest', self.suggest_places, methods=['GET'])

    def search_reports(self, request: Request, q: str = Query(min_length=1, max_length=120),
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        cache = search_cache(request)
        index, rebuilt = cache.get()
        started = time.perf_counter()
        matches, tokens = index.search(q)
        page = matches[offset:offset + limit]
        return {'reports': page, 'total': len(matches), 'hasMore': offset + len(page) < len(matches), 'tokens': tokens,
                'tookMs': round((time.perf_counter() - started) * 1000, 2),
                'index': {**index.stats(), 'builtAt': cache.built_at, 'buildMs': cache.build_ms, 'rebuilt': rebuilt}}

    def suggest_places(self, request: Request, prefix: str = Query(min_length=1, max_length=60),
                       limit: int = Query(8, ge=1, le=20)):
        index, _ = search_cache(request).get()
        return {'suggestions': index.suggest(prefix, limit)}
