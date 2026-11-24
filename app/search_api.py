"""Server-side report search and place suggestions.

Design pattern: Proxy. ``CachedReportSearch`` offers the same interface as
``ReportSearchIndex`` (``search``, ``suggest``, ``stats``) and controls access to
it: the real index is built lazily and rebuilt only when a cheap database
fingerprint (number and latest time of reports, status changes and passes)
changes. When any replica writes, every replica rebuilds on its next query, so
results never depend on which replica answers.
"""
import threading
import time
from typing import Literal, Protocol
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from .auth import SessionGuard
from .repository import PotholeStatus
from .search_index import ReportSearchIndex
from .timing import measured
from . import schema as s

ACTIVE_STATUSES = [status for status in PotholeStatus.ALL if status not in PotholeStatus.INACTIVE]


class ReportSearch(Protocol):
    """Subject interface shared by the real index and its proxy."""

    def search(self, query: str) -> tuple[list[dict], list[str]]: ...
    def filter(self, query: str | None = None, risk: list[str] | None = None, damage: list[str] | None = None,
               since: int | None = None, until: int | None = None) -> dict: ...
    def suggest(self, prefix: str, limit: int) -> list[dict]: ...
    def stats(self) -> dict: ...


class CachedReportSearch:
    """Proxy: same interface as ReportSearchIndex, rebuilt only when the data changed."""

    MAX_REPORTS = 10_000

    def __init__(self, engine, repo):
        self.engine, self.repo = engine, repo
        self.lock = threading.Lock()
        self.fingerprint = None
        self.index: ReportSearchIndex | None = None
        self.built_at = 0
        self.build_ms = 0.0
        self.rebuilt = False

    def _fingerprint(self) -> tuple:
        with self.engine.connect() as conn:
            reports = conn.execute(select(func.count(), func.max(s.reports.c.created_at))).one()
            events = conn.execute(select(func.count(), func.max(s.status_events.c.created_at))).one()
            zones = conn.execute(select(func.max(s.zones.c.resolved_at))).scalar_one()
            passes = conn.execute(select(func.count(), func.max(s.pothole_passes.c.created_at))).one()
        # Passes are included because results carry people and pass counts.
        return (*reports, *events, zones, *passes)

    def _subject(self) -> ReportSearchIndex:
        fingerprint = self._fingerprint()
        with self.lock:
            self.rebuilt = self.index is None or fingerprint != self.fingerprint
            if self.rebuilt:
                started = time.perf_counter()
                # Same visibility as GET /api/reports: active potholes only.
                reports, _ = self.repo.list_reports(self.MAX_REPORTS, 0, statuses=ACTIVE_STATUSES)
                self.index = ReportSearchIndex(reports)
                self.fingerprint, self.built_at = fingerprint, s.Clock.now()
                self.build_ms = round((time.perf_counter() - started) * 1000, 1)
            return self.index

    def search(self, query: str) -> tuple[list[dict], list[str]]:
        return self._subject().search(query)

    def filter(self, query: str | None = None, risk: list[str] | None = None, damage: list[str] | None = None,
               since: int | None = None, until: int | None = None) -> dict:
        return self._subject().filter(query, risk, damage, since, until)

    def suggest(self, prefix: str, limit: int) -> list[dict]:
        return self._subject().suggest(prefix, limit)

    def stats(self) -> dict:
        subject = self.index or self._subject()
        return {**subject.stats(), 'builtAt': self.built_at, 'buildMs': self.build_ms, 'rebuilt': self.rebuilt}


def report_search(request: Request) -> ReportSearch:
    state = request.app.state
    if getattr(state, 'report_search', None) is None:
        state.report_search = CachedReportSearch(state.engine, state.repo)
    return state.report_search


class SearchController:
    """GET /api/reports/search and /api/reports/suggest; a session is required."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/reports', dependencies=[Depends(SessionGuard.current)])
        self.router.add_api_route('/search', self.search_reports, methods=['GET'])
        self.router.add_api_route('/suggest', self.suggest_places, methods=['GET'])

    @measured()
    def search_reports(self, request: Request, q: str | None = Query(None, min_length=1, max_length=120),
                       risk: list[Literal['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']] = Query(default=[]),
                       damage: list[Literal['BACHE', 'HUNDIMIENTO', 'GRIETA', 'OTRO_DANO']] = Query(default=[]),
                       since: int | None = Query(None, alias='from', ge=0), until: int | None = Query(None, alias='to', ge=0),
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        if q is None and not risk and not damage and since is None and until is None:
            raise HTTPException(422, 'Escribe un texto o elige al menos un filtro.')
        if since is not None and until is not None and since > until:
            raise HTTPException(422, 'La fecha inicial no puede ser posterior a la final.')
        search = report_search(request)
        result = search.filter(q, risk, damage, since, until)
        matches = result['reports']
        page = matches[offset:offset + limit]
        return {'reports': page, 'total': len(matches), 'hasMore': offset + len(page) < len(matches), 'tokens': result['tokens'],
                'facets': result['facets'], 'index': search.stats()}

    def suggest_places(self, request: Request, prefix: str = Query(min_length=1, max_length=60),
                       limit: int = Query(8, ge=1, le=20)):
        return {'suggestions': report_search(request).suggest(prefix, limit)}
