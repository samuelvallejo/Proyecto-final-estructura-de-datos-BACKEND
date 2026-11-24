"""Profile, per-session history, pothole passes, the general map and the data dashboard."""
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from . import schema as s
from .contracts import Position
from .auth import SessionGuard
from .repository import PassTracker, PotholeStatus
from .structures import HashMap, HashSet, SinglyLinkedList, Sorter

DAY_MS = 86_400_000
LOCAL_TZ = timezone(timedelta(hours=-5))  # Colombia time, no daylight saving.


class AccountFormat:
    @staticmethod
    def initials(name):
        """Avatar initials from the first two words of the name, or 'BS'."""
        letters = ''
        for part in (name or '').replace('.', ' ').split():
            letters += part[0]
            if len(letters) == 2:
                break
        return letters.upper() or 'BS'

    @staticmethod
    def decrypt(vault, value):
        try:
            return vault.decrypt(value)
        except Exception:  # Legacy plain data or a rotated key must never break the profile.
            return ''


class SessionHistory:
    """Login sessions with their duration, scans, potholes and audit trail."""

    @staticmethod
    def of_user(user_id):
        return select(s.sessions.c.id).select_from(s.sessions.join(s.devices)).where(s.devices.c.user_id == user_id)

    @staticmethod
    def columns():
        return (s.sessions.c.id, s.sessions.c.created_at, s.sessions.c.ended_at, s.sessions.c.last_seen_at,
                s.sessions.c.expires_at, s.devices.c.user_id)

    @staticmethod
    def grouped_counts(conn, column, ids, *conditions) -> HashMap:
        counts = HashMap()
        if ids:
            for key, value in conn.execute(select(column, func.count()).where(column.in_(ids), *conditions).group_by(column)):
                counts[key] = value
        return counts

    @staticmethod
    def summaries(conn, rows, current_id=None, events=0):
        ids = [row['id'] for row in rows]
        now = s.Clock.now()
        scans = SessionHistory.grouped_counts(conn, s.api_usage.c.session_id, ids, s.api_usage.c.status == 'done')
        reports = SessionHistory.grouped_counts(conn, s.reports.c.session_id, ids)
        passes = SessionHistory.grouped_counts(conn, s.pothole_passes.c.session_id, ids)
        trips = SessionHistory.grouped_counts(conn, s.trips.c.session_id, ids)
        trail = HashMap[str, SinglyLinkedList]()
        if events and ids:
            query = (select(s.audit_events.c.session_id, s.audit_events.c.action, s.audit_events.c.created_at,
                            s.audit_events.c.entity_id, s.audit_events.c.details)
                     .where(s.audit_events.c.session_id.in_(ids))
                     .order_by(s.audit_events.c.created_at.desc()).limit(events * len(ids)))
            for event in conn.execute(query).mappings():
                bucket = trail.setdefault(event['session_id'], SinglyLinkedList)
                if bucket.size < events:
                    bucket.append({'action': event['action'], 'at': event['created_at'], 'entityId': event['entity_id'],
                                   'details': event['details'] or {}})
        result = SinglyLinkedList[dict]()
        for row in rows:
            active = row['ended_at'] is None and row['expires_at'] > now
            end = now if row['id'] == current_id else row['ended_at'] or row['last_seen_at'] or row['created_at']
            result.append({'id': row['id'], 'startedAt': row['created_at'], 'endedAt': row['ended_at'],
                           'lastSeenAt': row['last_seen_at'], 'active': active, 'current': row['id'] == current_id,
                           'durationMs': max(0, end - row['created_at']), 'scans': scans.get(row['id'], 0),
                           'potholesDetected': reports.get(row['id'], 0), 'potholesPassed': passes.get(row['id'], 0),
                           'trips': trips.get(row['id'], 0), 'events': list(trail.get(row['id']) or [])})
        return list(result)


class PassPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    position: Position
    tripId: UUID | None = None


class ProfileService:
    PASS_MAX_ACCURACY_M = 50

    def __init__(self, engine, vault, repository, settings):
        self.engine, self.vault, self.repository, self.settings = engine, vault, repository, settings

    def stats(self, conn, user_id):
        sessions = SessionHistory.of_user(user_id)

        def count(relation, *where):
            return conn.execute(select(func.count()).select_from(relation).where(*where)).scalar_one()
        return {
            'sessions': count(s.sessions.join(s.devices), s.devices.c.user_id == user_id),
            'scans': count(s.api_usage, s.api_usage.c.session_id.in_(sessions), s.api_usage.c.status == 'done'),
            'potholesDetected': count(s.reports, s.reports.c.session_id.in_(sessions)),
            'potholesPassed': conn.execute(select(func.count(func.distinct(s.pothole_passes.c.pothole_id)))
                                           .where(s.pothole_passes.c.user_id == user_id)).scalar_one(),
            'passes': count(s.pothole_passes, s.pothole_passes.c.user_id == user_id),
            'trips': count(s.trips, s.trips.c.user_id == user_id),
            'drivingMs': conn.execute(select(func.coalesce(func.sum(s.trips.c.ended_at - s.trips.c.created_at), 0))
                                      .where(s.trips.c.user_id == user_id, s.trips.c.ended_at.is_not(None))).scalar_one(),
        }

    def me(self, session):
        with self.engine.connect() as conn:
            user = conn.execute(select(s.users).where(s.users.c.id == session['user_id'])).mappings().one()
            name = AccountFormat.decrypt(self.vault, user['display_name'])
            return {'id': user['id'], 'displayName': name, 'email': AccountFormat.decrypt(self.vault, user['email']),
                    'initials': AccountFormat.initials(name), 'role': session['role'],
                    'isAdmin': session['role'] == 'Administrador', 'createdAt': user['created_at'],
                    'sessionId': session['id'], 'stats': self.stats(conn, session['user_id'])}

    def sessions(self, session, limit):
        with self.engine.connect() as conn:
            rows = conn.execute(select(*SessionHistory.columns()).select_from(s.sessions.join(s.devices))
                                .where(s.devices.c.user_id == session['user_id'])
                                .order_by(s.sessions.c.created_at.desc()).limit(limit)).mappings().all()
            return SessionHistory.summaries(conn, rows, session['id'], events=25)

    def pothole_history(self, session):
        """Potholes the user detected plus known potholes the user passed by, newest first."""
        repository = self.repository
        with self.engine.connect() as conn:
            detected = repository.with_stats(conn, conn.execute(repository.query().where(
                s.reports.c.session_id.in_(SessionHistory.of_user(session['user_id'])))
                .order_by(s.reports.c.created_at.desc()).limit(150)).mappings().all())
            passes = conn.execute(select(s.pothole_passes).where(s.pothole_passes.c.user_id == session['user_id'])
                                  .order_by(s.pothole_passes.c.created_at.desc()).limit(300)).mappings().all()
            passed_ids = list(HashSet(row['pothole_id'] for row in passes))
            by_pothole = HashMap[str, dict]()
            if passed_ids:
                rows = conn.execute(repository.query().where(s.potholes.c.id.in_(passed_ids))
                                    .order_by(s.reports.c.created_at)).mappings().all()
                for report in repository.with_stats(conn, rows):
                    by_pothole[report['potholeId']] = report
        history = SinglyLinkedList[dict]()
        for report in detected:
            history.append({'kind': 'detected', 'at': report['timestamp'], 'source': report['source'], 'report': report,
                            'tripId': None, 'distanceMeters': None})
        for row in passes:
            if row['pothole_id'] in by_pothole:
                history.append({'kind': 'passed', 'at': row['created_at'], 'source': row['source'],
                                'report': by_pothole[row['pothole_id']], 'tripId': row['trip_id'],
                                'distanceMeters': row['distance_m']})
        ordered = Sorter.merge_sort(history, key=lambda item: item['at'], reverse=True)
        return {'history': [item for index, item in enumerate(ordered) if index < 300],
                'detected': len(detected), 'passed': len(by_pothole)}

    def record_pass(self, payload: PassPayload, session):
        position = payload.position.model_dump()
        trip_id = str(payload.tripId) if payload.tripId else None
        radius = self.settings.pass_radius_meters
        with self.engine.begin() as conn:
            if trip_id:
                from .trips import TripService
                TripService.owned(conn, trip_id, session['user_id'], active=True)
            hits = PassTracker.nearby(conn, position, radius)
            # A GPS accuracy worse than 50 m cannot prove the person passed over the hole.
            saved = PassTracker.record(conn, session['user_id'], session['id'], hits, 'trip' if trip_id else 'gps', trip_id) \
                if position['accuracy'] <= self.PASS_MAX_ACCURACY_M else []
        return {'passed': len(saved), 'nearby': len(hits), 'radiusMeters': radius}

    def general_map(self, include):
        """Every registered pothole with how many people passed by it."""
        statuses = PotholeStatus.ALL if include == 'all' else ['UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS']
        reports, total = self.repository.list_reports(1000, 0, statuses=statuses)
        with self.engine.connect() as conn:
            people = conn.execute(select(func.count(func.distinct(s.pothole_passes.c.user_id)))).scalar_one()
            passes_total = conn.execute(select(func.count()).select_from(s.pothole_passes)).scalar_one()
        return {'potholes': reports, 'total': total, 'loaded': len(reports), 'peopleTotal': people,
                'passesTotal': passes_total, 'generatedAt': s.Clock.now()}


class DashboardService:
    """Each dashboard section is queried on its own so the client can show how data loads."""

    def __init__(self, engine, repository, pipeline, ai, settings):
        self.engine, self.repository, self.pipeline, self.ai, self.settings = engine, repository, pipeline, ai, settings

    @staticmethod
    def daily(conn, column, days, *where):
        """Counts per local calendar day for the last ``days`` days, oldest first."""
        today = datetime.now(LOCAL_TZ).date()
        first = today - timedelta(days=days - 1)
        since = int(datetime(first.year, first.month, first.day, tzinfo=LOCAL_TZ).timestamp() * 1000)
        offset = int(LOCAL_TZ.utcoffset(None).total_seconds() * 1000)
        bucket = func.floor((column + offset) / DAY_MS)
        counts = HashMap()
        for day, value in conn.execute(select(bucket, func.count()).where(column >= since, *where).group_by(bucket)):
            counts[int(day)] = value
        epoch = datetime(1970, 1, 1).date()
        values = [counts.get((first + timedelta(days=index) - epoch).days, 0) for index in range(days)]
        labels = [(first + timedelta(days=index)).isoformat() for index in range(days)]
        return values, labels

    def section(self, name, days):
        started = time.perf_counter()
        now = s.Clock.now()
        with self.engine.connect() as conn:
            def count(relation, *where):
                return conn.execute(select(func.count()).select_from(relation).where(*where)).scalar_one()
            if name == 'totals':
                data = {
                    'potholesActive': count(s.potholes, s.potholes.c.status.not_in(PotholeStatus.INACTIVE)),
                    'potholesRepaired': count(s.potholes, s.potholes.c.status == 'REPAIRED'),
                    'reports': count(s.reports),
                    'communityReports': count(s.risk_assessments, s.risk_assessments.c.method == 'community'),
                    'users': count(s.users),
                    'people': conn.execute(select(func.count(func.distinct(s.pothole_passes.c.user_id)))).scalar_one(),
                    'passes': count(s.pothole_passes),
                    'scans': count(s.api_usage, s.api_usage.c.status == 'done'),
                    'scans24h': count(s.api_usage, s.api_usage.c.status == 'done', s.api_usage.c.created_at > now - DAY_MS),
                    'trips': count(s.trips),
                    'activeSessions': count(s.sessions, s.sessions.c.ended_at.is_(None), s.sessions.c.expires_at > now,
                                            s.sessions.c.last_seen_at > now - 15 * 60_000),
                }
            elif name == 'series':
                reports, labels = self.daily(conn, s.reports.c.created_at, days)
                scans, _ = self.daily(conn, s.api_usage.c.created_at, days, s.api_usage.c.status == 'done')
                passes, _ = self.daily(conn, s.pothole_passes.c.created_at, days)
                data = {'days': labels, 'reports': reports, 'scans': scans, 'passes': passes}
            elif name == 'risk':
                levels = conn.execute(select(s.risk_assessments.c.level, func.count())
                                      .select_from(s.risk_assessments.join(s.potholes, s.risk_assessments.c.pothole_id == s.potholes.c.id))
                                      .where(s.potholes.c.status.not_in(PotholeStatus.INACTIVE))
                                      .group_by(s.risk_assessments.c.level)).all()
                statuses = conn.execute(select(s.potholes.c.status, func.count()).group_by(s.potholes.c.status)).all()
                data = {'levels': {level: value for level, value in levels}, 'statuses': {status: value for status, value in statuses}}
            elif name == 'top':
                people = func.count(func.distinct(s.pothole_passes.c.user_id))
                top = conn.execute(select(s.pothole_passes.c.pothole_id, people.label('people'), func.count().label('passes'))
                                   .group_by(s.pothole_passes.c.pothole_id).order_by(people.desc(), func.count().desc())
                                   .limit(5)).mappings().all()
                by_pothole = HashMap[str, dict]()
                if top:
                    rows = conn.execute(self.repository.query().where(s.potholes.c.id.in_([row['pothole_id'] for row in top]))).mappings().all()
                    for report in self.repository.with_stats(conn, rows):
                        by_pothole[report['potholeId']] = report
                data = {'potholes': [by_pothole[row['pothole_id']] for row in top if row['pothole_id'] in by_pothole]}
            else:
                stats = self.pipeline.stats()
                data = {'queue': stats['queue'], 'latency': stats.get('totalLatencyMs'),
                        'modelLatency': self.ai.latency_summary() if hasattr(self.ai, 'latency_summary') else None,
                        'liveImageSize': self.settings.yolo_live_image_size,
                        'photoImageSize': self.settings.yolo_image_size,
                        'nextScanMs': round(self.settings.local_scan_interval_seconds * 1000)}
        return {'section': name, 'data': data, 'serverMs': round((time.perf_counter() - started) * 1000, 1), 'generatedAt': now}


Section = Literal['totals', 'series', 'risk', 'top', 'pipeline']


class ProfileController:
    def __init__(self):
        self.router = APIRouter(prefix='/api')
        self.router.add_api_route('/me', self.me, methods=['GET'])
        self.router.add_api_route('/me/sessions', self.my_sessions, methods=['GET'])
        self.router.add_api_route('/me/potholes', self.my_potholes, methods=['GET'])
        self.router.add_api_route('/passes', self.passes, methods=['POST'])
        self.router.add_api_route('/map/potholes', self.general_map, methods=['GET'])
        self.router.add_api_route('/dashboard', self.dashboard, methods=['GET'])

    @staticmethod
    def _profile(request: Request) -> ProfileService:
        return request.app.state.profile

    def me(self, request: Request, session=Depends(SessionGuard.current)):
        return self._profile(request).me(session)

    def my_sessions(self, request: Request, limit: int = Query(30, ge=1, le=100), session=Depends(SessionGuard.current)):
        return {'sessions': self._profile(request).sessions(session, limit)}

    def my_potholes(self, request: Request, session=Depends(SessionGuard.current)):
        return self._profile(request).pothole_history(session)

    def passes(self, payload: PassPayload, request: Request, session=Depends(SessionGuard.current)):
        return self._profile(request).record_pass(payload, session)

    def general_map(self, request: Request, include: Literal['active', 'all'] = 'all', session=Depends(SessionGuard.current)):
        return self._profile(request).general_map(include)

    def dashboard(self, request: Request, section: Section = 'totals', days: int = Query(14, ge=7, le=60),
                  session=Depends(SessionGuard.current)):
        return request.app.state.dashboard.section(section, days)
