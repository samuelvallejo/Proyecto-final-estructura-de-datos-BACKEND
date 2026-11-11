"""Modo administrador: ve todos los datos y gestiona cuentas, roles y estados de baches."""
import json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from .auth import ROLES, audit, require_admin, role_of, set_role
from .profile import ALL_STATUSES, DAY_MS, decrypt, grouped_counts, initials, session_columns, session_summaries
from .trips import trip_metrics
from . import schema as s

router = APIRouter(prefix='/api/admin', dependencies=[Depends(require_admin)])


class RoleChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['Administrador', 'Operario', 'Conductor']


class ActiveChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool


class StatusChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS', 'REPAIRED', 'REJECTED']
    reason: str = Field(default='', max_length=280)


def user_names(conn, vault, user_ids):
    ids = [identity for identity in set(user_ids) if identity]
    if not ids:
        return {}
    rows = conn.execute(select(s.users.c.id, s.users.c.display_name).where(s.users.c.id.in_(ids))).all()
    return {identity: decrypt(vault, name) for identity, name in rows}


@router.get('/overview')
def overview(request: Request):
    now = s.now()
    with request.app.state.engine.connect() as conn:
        count = lambda relation, *where: conn.execute(select(func.count()).select_from(relation).where(*where)).scalar_one()
        roles = {name: 0 for name in ROLES}
        users = conn.execute(select(s.users.c.id)).scalars().all()
        for user_id in users:
            roles[role_of(conn, user_id)] += 1
        statuses = dict(conn.execute(select(s.potholes.c.status, func.count()).group_by(s.potholes.c.status)).all())
        return {
            'users': len(users), 'inactiveUsers': count(s.users, s.users.c.active.is_(False)), 'roles': roles,
            'activeSessions': count(s.sessions, s.sessions.c.ended_at.is_(None), s.sessions.c.expires_at > now,
                                    s.sessions.c.last_seen_at > now - 15 * 60_000),
            'sessions24h': count(s.sessions, s.sessions.c.created_at > now - DAY_MS),
            'statuses': {status: statuses.get(status, 0) for status in ALL_STATUSES},
            'reports': count(s.reports),
            'scans24h': count(s.api_usage, s.api_usage.c.status == 'done', s.api_usage.c.created_at > now - DAY_MS),
            'failedScans24h': count(s.api_usage, s.api_usage.c.status == 'failed', s.api_usage.c.created_at > now - DAY_MS),
            'passes': count(s.pothole_passes),
            'activeTrips': count(s.trips, s.trips.c.ended_at.is_(None)),
            'auditEvents24h': count(s.audit_events, s.audit_events.c.created_at > now - DAY_MS),
            'generatedAt': now,
        }


@router.get('/users')
def users(request: Request, limit: int = Query(200, ge=1, le=500)):
    vault = request.app.state.vault
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(select(s.users).order_by(s.users.c.created_at.desc()).limit(limit)).mappings().all()
        ids = [row['id'] for row in rows]
        last_seen = dict(conn.execute(select(s.devices.c.user_id, func.max(func.coalesce(s.sessions.c.last_seen_at, s.sessions.c.created_at)))
                                      .select_from(s.sessions.join(s.devices)).where(s.devices.c.user_id.in_(ids))
                                      .group_by(s.devices.c.user_id)).all()) if ids else {}
        sessions = dict(conn.execute(select(s.devices.c.user_id, func.count()).select_from(s.sessions.join(s.devices))
                                     .where(s.devices.c.user_id.in_(ids)).group_by(s.devices.c.user_id)).all()) if ids else {}
        reports = dict(conn.execute(select(s.devices.c.user_id, func.count()).select_from(
            s.reports.join(s.sessions, s.reports.c.session_id == s.sessions.c.id).join(s.devices))
            .where(s.devices.c.user_id.in_(ids)).group_by(s.devices.c.user_id)).all()) if ids else {}
        passes = grouped_counts(conn, s.pothole_passes.c.user_id, ids)
        trips = grouped_counts(conn, s.trips.c.user_id, ids)
        result = []
        for row in rows:
            name = decrypt(vault, row['display_name'])
            result.append({'id': row['id'], 'displayName': name, 'initials': initials(name),
                           'email': decrypt(vault, row['email']), 'role': role_of(conn, row['id']), 'active': row['active'],
                           'createdAt': row['created_at'], 'lastSeenAt': last_seen.get(row['id']),
                           'sessions': sessions.get(row['id'], 0), 'reports': reports.get(row['id'], 0),
                           'passes': passes.get(row['id'], 0), 'trips': trips.get(row['id'], 0)})
    return {'users': result}


def admin_count(conn):
    return sum(1 for user_id in conn.execute(select(s.users.c.id).where(s.users.c.active.is_(True))).scalars()
               if role_of(conn, user_id) == 'Administrador')


@router.post('/users/{user_id}/role')
def change_role(user_id: UUID, payload: RoleChange, request: Request, admin=Depends(require_admin)):
    user_id = str(user_id)
    with request.app.state.engine.begin() as conn:
        if not conn.execute(select(s.users.c.id).where(s.users.c.id == user_id)).first():
            raise HTTPException(404, 'La cuenta no existe.')
        previous = role_of(conn, user_id)
        if previous == 'Administrador' and payload.role != 'Administrador' and admin_count(conn) <= 1:
            raise HTTPException(409, 'Debe quedar al menos un administrador activo.')
        set_role(conn, user_id, payload.role)
        audit(conn, admin['id'], 'admin.user.role', user_id, {'from': previous, 'to': payload.role})
    return {'id': user_id, 'role': payload.role}


@router.post('/users/{user_id}/active')
def change_active(user_id: UUID, payload: ActiveChange, request: Request, admin=Depends(require_admin)):
    user_id = str(user_id)
    if user_id == admin['user_id'] and not payload.active:
        raise HTTPException(409, 'No puedes desactivar tu propia cuenta.')
    now = s.now()
    with request.app.state.engine.begin() as conn:
        if not conn.execute(select(s.users.c.id).where(s.users.c.id == user_id)).first():
            raise HTTPException(404, 'La cuenta no existe.')
        if not payload.active and role_of(conn, user_id) == 'Administrador' and admin_count(conn) <= 1:
            raise HTTPException(409, 'Debe quedar al menos un administrador activo.')
        conn.execute(update(s.users).where(s.users.c.id == user_id).values(active=payload.active))
        if not payload.active:
            # Cerrar de inmediato las sesiones abiertas de la cuenta desactivada.
            devices = select(s.devices.c.id).where(s.devices.c.user_id == user_id)
            conn.execute(update(s.sessions).where(s.sessions.c.device_id.in_(devices), s.sessions.c.ended_at.is_(None))
                         .values(expires_at=0, ended_at=now))
        audit(conn, admin['id'], 'admin.user.active', user_id, {'active': payload.active})
    return {'id': user_id, 'active': payload.active}


@router.get('/reports')
def all_reports(request: Request, status: Literal['all', 'UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS', 'REPAIRED', 'REJECTED'] = 'all',
                limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    statuses = ALL_STATUSES if status == 'all' else [status]
    items, total = request.app.state.repo.list_reports(limit, offset, statuses=statuses)
    return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}


@router.post('/reports/{report_id}/status')
def change_status(report_id: UUID, payload: StatusChange, request: Request, admin=Depends(require_admin)):
    with request.app.state.engine.begin() as conn:
        pothole = conn.execute(select(s.potholes.c.id, s.potholes.c.status).select_from(
            s.reports.join(s.potholes, s.reports.c.pothole_id == s.potholes.c.id))
            .where(s.reports.c.id == str(report_id))).mappings().first()
        if not pothole:
            raise HTTPException(404, 'El reporte no existe.')
        if pothole['status'] != payload.status:
            conn.execute(update(s.potholes).where(s.potholes.c.id == pothole['id']).values(status=payload.status))
            conn.execute(s.status_events.insert().values(pothole_id=pothole['id'], actor_id=admin['user_id'],
                old_status=pothole['status'], new_status=payload.status,
                reason=payload.reason.strip() or 'Cambio realizado por administración'))
            audit(conn, admin['id'], 'admin.report.status', str(report_id), {'from': pothole['status'], 'to': payload.status})
    return request.app.state.repo.get_report(str(report_id))


@router.get('/sessions')
def all_sessions(request: Request, limit: int = Query(100, ge=1, le=300)):
    vault = request.app.state.vault
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(select(*session_columns()).select_from(s.sessions.join(s.devices))
                            .where(s.devices.c.user_id.is_not(None))
                            .order_by(s.sessions.c.created_at.desc()).limit(limit)).mappings().all()
        summaries = session_summaries(conn, rows, events=12)
        names = user_names(conn, vault, [row['user_id'] for row in rows])
    for summary, row in zip(summaries, rows):
        summary['userId'] = row['user_id']
        summary['userName'] = names.get(row['user_id'], '')
    return {'sessions': summaries}


@router.get('/audit')
def audit_trail(request: Request, limit: int = Query(150, ge=1, le=500)):
    vault = request.app.state.vault
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(select(s.audit_events.c.id, s.audit_events.c.action, s.audit_events.c.created_at,
                                   s.audit_events.c.entity_id, s.audit_events.c.details, s.audit_events.c.session_id,
                                   s.devices.c.user_id)
                            .select_from(s.audit_events.outerjoin(s.sessions, s.audit_events.c.session_id == s.sessions.c.id)
                                         .outerjoin(s.devices, s.sessions.c.device_id == s.devices.c.id))
                            .order_by(s.audit_events.c.created_at.desc()).limit(limit)).mappings().all()
        names = user_names(conn, vault, [row['user_id'] for row in rows])
    return {'events': [{'id': row['id'], 'action': row['action'], 'at': row['created_at'], 'entityId': row['entity_id'],
                        'details': row['details'] or {}, 'sessionId': row['session_id'], 'userId': row['user_id'],
                        'userName': names.get(row['user_id'], '')} for row in rows]}


@router.get('/trips')
def all_trips(request: Request, limit: int = Query(100, ge=1, le=300)):
    vault = request.app.state.vault
    now = s.now()
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(select(s.trips).order_by(s.trips.c.created_at.desc()).limit(limit)).mappings().all()
        names = user_names(conn, vault, [row['user_id'] for row in rows])
        result = []
        for row in rows:
            try:
                data = json.loads(vault.decrypt(row['encrypted_details']))
            except Exception:
                data = {}
            result.append({'id': row['id'], 'userId': row['user_id'], 'userName': names.get(row['user_id'], ''),
                           'name': data.get('name', ''), 'pointA': data.get('pointA', ''), 'pointB': data.get('pointB', ''),
                           'vehicle': data.get('vehicle'), 'startedAt': row['created_at'], 'endedAt': row['ended_at'],
                           'durationMs': max(0, (row['ended_at'] or now) - row['created_at']), **trip_metrics(conn, row['id'])})
    return {'trips': result}
