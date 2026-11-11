"""Perfil, historial por sesión, pasos por baches, mapa general y panel de datos."""
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from .auth import current_session, audit
from .contracts import Position
from .repository import nearby_potholes, record_passes
from . import schema as s

router = APIRouter(prefix='/api')
DAY_MS = 86_400_000
LOCAL_TZ = timezone(timedelta(hours=-5))  # Hora de Colombia, sin horario de verano.
ALL_STATUSES = ['UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS', 'REPAIRED', 'REJECTED']


def initials(name):
    parts = [part for part in (name or '').replace('.', ' ').split() if part]
    letters = ''.join(part[0] for part in parts[:2]).upper()
    return letters or 'BS'


def decrypt(vault, value):
    try:
        return vault.decrypt(value)
    except Exception:  # Datos heredados sin cifrar o clave rotada: nunca romper el perfil.
        return ''


def user_sessions_query(user_id):
    return select(s.sessions.c.id).select_from(s.sessions.join(s.devices)).where(s.devices.c.user_id == user_id)


def grouped_counts(conn, column, ids, *conditions):
    if not ids:
        return {}
    rows = conn.execute(select(column, func.count()).where(column.in_(ids), *conditions).group_by(column)).all()
    return {key: value for key, value in rows}


def session_summaries(conn, rows, current_id=None, events=0):
    """Duración, escaneos, baches y huella de eventos de cada sesión de inicio."""
    ids = [row['id'] for row in rows]
    now = s.now()
    scans = grouped_counts(conn, s.api_usage.c.session_id, ids, s.api_usage.c.status == 'done')
    reports = grouped_counts(conn, s.reports.c.session_id, ids)
    passes = grouped_counts(conn, s.pothole_passes.c.session_id, ids)
    trips = grouped_counts(conn, s.trips.c.session_id, ids)
    trail = {}
    if events and ids:
        for event in conn.execute(select(s.audit_events.c.session_id, s.audit_events.c.action, s.audit_events.c.created_at,
                                         s.audit_events.c.entity_id, s.audit_events.c.details)
                                  .where(s.audit_events.c.session_id.in_(ids))
                                  .order_by(s.audit_events.c.created_at.desc()).limit(events * len(ids))).mappings():
            bucket = trail.setdefault(event['session_id'], [])
            if len(bucket) < events:
                bucket.append({'action': event['action'], 'at': event['created_at'], 'entityId': event['entity_id'],
                               'details': event['details'] or {}})
    result = []
    for row in rows:
        active = row['ended_at'] is None and row['expires_at'] > now
        end = now if row['id'] == current_id else row['ended_at'] or row['last_seen_at'] or row['created_at']
        result.append({'id': row['id'], 'startedAt': row['created_at'], 'endedAt': row['ended_at'],
                       'lastSeenAt': row['last_seen_at'], 'active': active, 'current': row['id'] == current_id,
                       'durationMs': max(0, end - row['created_at']), 'scans': scans.get(row['id'], 0),
                       'potholesDetected': reports.get(row['id'], 0), 'potholesPassed': passes.get(row['id'], 0),
                       'trips': trips.get(row['id'], 0), 'events': trail.get(row['id'], [])})
    return result


def session_columns():
    return (s.sessions.c.id, s.sessions.c.created_at, s.sessions.c.ended_at, s.sessions.c.last_seen_at,
            s.sessions.c.expires_at, s.devices.c.user_id)


def user_stats(conn, user_id):
    sessions = user_sessions_query(user_id)
    count = lambda relation, *where: conn.execute(select(func.count()).select_from(relation).where(*where)).scalar_one()
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


@router.get('/me')
def me(request: Request, session=Depends(current_session)):
    vault = request.app.state.vault
    with request.app.state.engine.connect() as conn:
        user = conn.execute(select(s.users).where(s.users.c.id == session['user_id'])).mappings().one()
        name = decrypt(vault, user['display_name'])
        return {'id': user['id'], 'displayName': name, 'email': decrypt(vault, user['email']), 'initials': initials(name),
                'role': session['role'], 'isAdmin': session['role'] == 'Administrador', 'createdAt': user['created_at'],
                'sessionId': session['id'], 'stats': user_stats(conn, session['user_id'])}


@router.get('/me/sessions')
def my_sessions(request: Request, limit: int = Query(30, ge=1, le=100), session=Depends(current_session)):
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(select(*session_columns()).select_from(s.sessions.join(s.devices))
                            .where(s.devices.c.user_id == session['user_id'])
                            .order_by(s.sessions.c.created_at.desc()).limit(limit)).mappings().all()
        return {'sessions': session_summaries(conn, rows, session['id'], events=25)}


@router.get('/me/potholes')
def my_potholes(request: Request, session=Depends(current_session)):
    repo = request.app.state.repo
    with request.app.state.engine.connect() as conn:
        detected = repo.with_stats(conn, conn.execute(repo.query().where(
            s.reports.c.session_id.in_(user_sessions_query(session['user_id'])))
            .order_by(s.reports.c.created_at.desc()).limit(150)).mappings().all())
        passes = conn.execute(select(s.pothole_passes).where(s.pothole_passes.c.user_id == session['user_id'])
                              .order_by(s.pothole_passes.c.created_at.desc()).limit(300)).mappings().all()
        passed_ids = list({row['pothole_id'] for row in passes})
        by_pothole = {report['potholeId']: report for report in repo.with_stats(conn, conn.execute(
            repo.query().where(s.potholes.c.id.in_(passed_ids)).order_by(s.reports.c.created_at)).mappings().all())} if passed_ids else {}
    history = [{'kind': 'detected', 'at': report['timestamp'], 'source': report['source'], 'report': report,
                'tripId': None, 'distanceMeters': None} for report in detected]
    history += [{'kind': 'passed', 'at': row['created_at'], 'source': row['source'], 'report': by_pothole[row['pothole_id']],
                 'tripId': row['trip_id'], 'distanceMeters': row['distance_m']}
                for row in passes if row['pothole_id'] in by_pothole]
    history.sort(key=lambda item: item['at'], reverse=True)
    return {'history': history[:300], 'detected': len(detected), 'passed': len(by_pothole)}


class PassPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    position: Position
    tripId: UUID | None = None


@router.post('/passes')
def passes(payload: PassPayload, request: Request, session=Depends(current_session)):
    position = payload.position.model_dump()
    trip_id = str(payload.tripId) if payload.tripId else None
    radius = request.app.state.settings.pass_radius_meters
    with request.app.state.engine.begin() as conn:
        if trip_id:
            from .trips import owned_trip
            owned_trip(conn, trip_id, session['user_id'], active=True)
        hits = nearby_potholes(conn, position, radius)
        # Una precisión GPS peor que 50 m no permite afirmar que la persona pasó por el hueco.
        saved = record_passes(conn, session['user_id'], session['id'], hits, 'trip' if trip_id else 'gps', trip_id) \
            if position['accuracy'] <= 50 else []
    return {'passed': len(saved), 'nearby': len(hits), 'radiusMeters': radius}


@router.get('/map/potholes')
def general_map(request: Request, include: Literal['active', 'all'] = 'all', session=Depends(current_session)):
    """Todos los huecos registrados con cuántas personas han pasado por cada uno."""
    repo = request.app.state.repo
    statuses = ALL_STATUSES if include == 'all' else ['UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS']
    reports, total = repo.list_reports(1000, 0, statuses=statuses)
    with request.app.state.engine.connect() as conn:
        people = conn.execute(select(func.count(func.distinct(s.pothole_passes.c.user_id)))).scalar_one()
        passes_total = conn.execute(select(func.count()).select_from(s.pothole_passes)).scalar_one()
    return {'potholes': reports, 'total': total, 'loaded': len(reports), 'peopleTotal': people, 'passesTotal': passes_total,
            'generatedAt': s.now()}


def local_day(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, LOCAL_TZ).date()


def daily(conn, column, days, *where):
    today = datetime.now(LOCAL_TZ).date()
    first = today - timedelta(days=days - 1)
    since = int(datetime(first.year, first.month, first.day, tzinfo=LOCAL_TZ).timestamp() * 1000)
    offset = int(LOCAL_TZ.utcoffset(None).total_seconds() * 1000)
    bucket = func.floor((column + offset) / DAY_MS)
    rows = dict(conn.execute(select(bucket, func.count()).where(column >= since, *where).group_by(bucket)).all())
    epoch = datetime(1970, 1, 1).date()
    return [rows.get((first + timedelta(days=index) - epoch).days, 0) for index in range(days)], \
        [(first + timedelta(days=index)).isoformat() for index in range(days)]


Section = Literal['totals', 'series', 'risk', 'top', 'pipeline']


@router.get('/dashboard')
def dashboard(request: Request, section: Section = 'totals', days: int = Query(14, ge=7, le=60),
              session=Depends(current_session)):
    """Cada sección se consulta por separado para mostrar cómo y en cuánto tiempo carga cada dato."""
    started = time.perf_counter()
    app = request.app
    now = s.now()
    with app.state.engine.connect() as conn:
        count = lambda relation, *where: conn.execute(select(func.count()).select_from(relation).where(*where)).scalar_one()
        if section == 'totals':
            data = {
                'potholesActive': count(s.potholes, s.potholes.c.status.not_in(['REPAIRED', 'REJECTED'])),
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
        elif section == 'series':
            reports, labels = daily(conn, s.reports.c.created_at, days)
            scans, _ = daily(conn, s.api_usage.c.created_at, days, s.api_usage.c.status == 'done')
            passes_series, _ = daily(conn, s.pothole_passes.c.created_at, days)
            data = {'days': labels, 'reports': reports, 'scans': scans, 'passes': passes_series}
        elif section == 'risk':
            rows = conn.execute(select(s.risk_assessments.c.level, func.count())
                                .select_from(s.risk_assessments.join(s.potholes, s.risk_assessments.c.pothole_id == s.potholes.c.id))
                                .where(s.potholes.c.status.not_in(['REPAIRED', 'REJECTED']))
                                .group_by(s.risk_assessments.c.level)).all()
            statuses = conn.execute(select(s.potholes.c.status, func.count()).group_by(s.potholes.c.status)).all()
            data = {'levels': {level: value for level, value in rows}, 'statuses': {status: value for status, value in statuses}}
        elif section == 'top':
            people = func.count(func.distinct(s.pothole_passes.c.user_id))
            top = conn.execute(select(s.pothole_passes.c.pothole_id, people.label('people'), func.count().label('passes'))
                               .group_by(s.pothole_passes.c.pothole_id).order_by(people.desc(), func.count().desc())
                               .limit(5)).mappings().all()
            reports = {report['potholeId']: report for report in app.state.repo.with_stats(conn, conn.execute(
                app.state.repo.query().where(s.potholes.c.id.in_([row['pothole_id'] for row in top]))).mappings().all())} if top else {}
            data = {'potholes': [reports[row['pothole_id']] for row in top if row['pothole_id'] in reports]}
        else:
            stats = app.state.pipeline.stats()
            data = {'queue': stats['queue'], 'latency': stats.get('totalLatencyMs'),
                    'modelLatency': app.state.ai.latency_summary() if hasattr(app.state.ai, 'latency_summary') else None,
                    'liveImageSize': app.state.settings.yolo_live_image_size,
                    'photoImageSize': app.state.settings.yolo_image_size,
                    'nextScanMs': round(app.state.settings.local_scan_interval_seconds * 1000)}
    return {'section': section, 'data': data, 'serverMs': round((time.perf_counter() - started) * 1000, 1),
            'generatedAt': now}


def log_scan(engine, session_id, detections, provider):
    """Huella de los análisis con hallazgos; los fotogramas vacíos ya cuentan en api_usage."""
    if not detections:
        return
    with engine.begin() as conn:
        audit(conn, session_id, 'scan.detected', details={'detections': detections, 'provider': provider})


def ensure_known_status(status):
    if status not in ALL_STATUSES:
        raise HTTPException(422, 'Estado desconocido.')
