"""Administrator mode: sees every record and manages accounts, roles and pothole statuses."""
import json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from . import schema as s
from .auth import AuditLog, Roles, SessionGuard
from .profile import DAY_MS, AccountFormat, SessionHistory
from .repository import PotholeStatus
from .structures import HashMap, HashSet, SinglyLinkedList
from .trips import TripService


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


class AdminService:
    def __init__(self, engine, vault, repository):
        self.engine, self.vault, self.repository = engine, vault, repository

    def _names(self, conn, user_ids) -> HashMap:
        names = HashMap[str, str]()
        ids = [identity for identity in HashSet(user_ids) if identity]
        if ids:
            for identity, name in conn.execute(select(s.users.c.id, s.users.c.display_name).where(s.users.c.id.in_(ids))):
                names[identity] = AccountFormat.decrypt(self.vault, name)
        return names

    @staticmethod
    def _active_admins(conn) -> int:
        return sum(1 for user_id in conn.execute(select(s.users.c.id).where(s.users.c.active.is_(True))).scalars()
                   if Roles.of(conn, user_id) == Roles.ADMIN)

    @staticmethod
    def _require_user(conn, user_id):
        if not conn.execute(select(s.users.c.id).where(s.users.c.id == user_id)).first():
            raise HTTPException(404, 'La cuenta no existe.')

    def overview(self):
        now = s.Clock.now()
        with self.engine.connect() as conn:
            def count(relation, *where):
                return conn.execute(select(func.count()).select_from(relation).where(*where)).scalar_one()
            roles = HashMap[str, int]((name, 0) for name in Roles.ALL)
            users = conn.execute(select(s.users.c.id)).scalars().all()
            for user_id in users:
                role = Roles.of(conn, user_id)
                roles[role] = roles[role] + 1
            statuses = HashMap(conn.execute(select(s.potholes.c.status, func.count()).group_by(s.potholes.c.status)).all())
            return {
                'users': len(users), 'inactiveUsers': count(s.users, s.users.c.active.is_(False)),
                'roles': {name: roles[name] for name in Roles.ALL},
                'activeSessions': count(s.sessions, s.sessions.c.ended_at.is_(None), s.sessions.c.expires_at > now,
                                        s.sessions.c.last_seen_at > now - 15 * 60_000),
                'sessions24h': count(s.sessions, s.sessions.c.created_at > now - DAY_MS),
                'statuses': {status: statuses.get(status, 0) for status in PotholeStatus.ALL},
                'reports': count(s.reports),
                'scans24h': count(s.api_usage, s.api_usage.c.status == 'done', s.api_usage.c.created_at > now - DAY_MS),
                'failedScans24h': count(s.api_usage, s.api_usage.c.status == 'failed', s.api_usage.c.created_at > now - DAY_MS),
                'passes': count(s.pothole_passes),
                'activeTrips': count(s.trips, s.trips.c.ended_at.is_(None)),
                'auditEvents24h': count(s.audit_events, s.audit_events.c.created_at > now - DAY_MS),
                'generatedAt': now,
            }

    def users(self, limit):
        with self.engine.connect() as conn:
            rows = conn.execute(select(s.users).order_by(s.users.c.created_at.desc()).limit(limit)).mappings().all()
            ids = [row['id'] for row in rows]
            last_seen, sessions, reports = HashMap(), HashMap(), HashMap()
            if ids:
                last_seen = HashMap(conn.execute(select(s.devices.c.user_id, func.max(func.coalesce(s.sessions.c.last_seen_at, s.sessions.c.created_at)))
                                                 .select_from(s.sessions.join(s.devices)).where(s.devices.c.user_id.in_(ids))
                                                 .group_by(s.devices.c.user_id)).all())
                sessions = HashMap(conn.execute(select(s.devices.c.user_id, func.count()).select_from(s.sessions.join(s.devices))
                                                .where(s.devices.c.user_id.in_(ids)).group_by(s.devices.c.user_id)).all())
                reports = HashMap(conn.execute(select(s.devices.c.user_id, func.count()).select_from(
                    s.reports.join(s.sessions, s.reports.c.session_id == s.sessions.c.id).join(s.devices))
                    .where(s.devices.c.user_id.in_(ids)).group_by(s.devices.c.user_id)).all())
            passes = SessionHistory.grouped_counts(conn, s.pothole_passes.c.user_id, ids)
            trips = SessionHistory.grouped_counts(conn, s.trips.c.user_id, ids)
            result = SinglyLinkedList[dict]()
            for row in rows:
                name = AccountFormat.decrypt(self.vault, row['display_name'])
                result.append({'id': row['id'], 'displayName': name, 'initials': AccountFormat.initials(name),
                               'email': AccountFormat.decrypt(self.vault, row['email']), 'role': Roles.of(conn, row['id']),
                               'active': row['active'], 'createdAt': row['created_at'], 'lastSeenAt': last_seen.get(row['id']),
                               'sessions': sessions.get(row['id'], 0), 'reports': reports.get(row['id'], 0),
                               'passes': passes.get(row['id'], 0), 'trips': trips.get(row['id'], 0)})
        return list(result)

    def change_role(self, user_id, role, admin):
        with self.engine.begin() as conn:
            self._require_user(conn, user_id)
            previous = Roles.of(conn, user_id)
            if previous == Roles.ADMIN and role != Roles.ADMIN and self._active_admins(conn) <= 1:
                raise HTTPException(409, 'Debe quedar al menos un administrador activo.')
            Roles.assign(conn, user_id, role)
            AuditLog.record(conn, admin['id'], 'admin.user.role', user_id, {'from': previous, 'to': role})
        return {'id': user_id, 'role': role}

    def change_active(self, user_id, active, admin):
        if user_id == admin['user_id'] and not active:
            raise HTTPException(409, 'No puedes desactivar tu propia cuenta.')
        with self.engine.begin() as conn:
            self._require_user(conn, user_id)
            if not active and Roles.of(conn, user_id) == Roles.ADMIN and self._active_admins(conn) <= 1:
                raise HTTPException(409, 'Debe quedar al menos un administrador activo.')
            conn.execute(update(s.users).where(s.users.c.id == user_id).values(active=active))
            if not active:
                # Close the open sessions of the deactivated account right away.
                devices = select(s.devices.c.id).where(s.devices.c.user_id == user_id)
                conn.execute(update(s.sessions).where(s.sessions.c.device_id.in_(devices), s.sessions.c.ended_at.is_(None))
                             .values(expires_at=0, ended_at=s.Clock.now()))
            AuditLog.record(conn, admin['id'], 'admin.user.active', user_id, {'active': active})
        return {'id': user_id, 'active': active}

    def reports(self, status, limit, offset):
        statuses = PotholeStatus.ALL if status == 'all' else [status]
        items, total = self.repository.list_reports(limit, offset, statuses=statuses)
        return {'reports': items, 'total': total, 'hasMore': offset + len(items) < total}

    def change_status(self, report_id, payload: StatusChange, admin):
        with self.engine.begin() as conn:
            pothole = conn.execute(select(s.potholes.c.id, s.potholes.c.status).select_from(
                s.reports.join(s.potholes, s.reports.c.pothole_id == s.potholes.c.id))
                .where(s.reports.c.id == report_id)).mappings().first()
            if not pothole:
                raise HTTPException(404, 'El reporte no existe.')
            if pothole['status'] != payload.status:
                conn.execute(update(s.potholes).where(s.potholes.c.id == pothole['id']).values(status=payload.status))
                conn.execute(s.status_events.insert().values(pothole_id=pothole['id'], actor_id=admin['user_id'],
                    old_status=pothole['status'], new_status=payload.status,
                    reason=payload.reason.strip() or 'Cambio realizado por administración'))
                AuditLog.record(conn, admin['id'], 'admin.report.status', report_id, {'from': pothole['status'], 'to': payload.status})
        return self.repository.get_report(report_id)

    def sessions(self, limit):
        with self.engine.connect() as conn:
            rows = conn.execute(select(*SessionHistory.columns()).select_from(s.sessions.join(s.devices))
                                .where(s.devices.c.user_id.is_not(None))
                                .order_by(s.sessions.c.created_at.desc()).limit(limit)).mappings().all()
            summaries = SessionHistory.summaries(conn, rows, events=12)
            names = self._names(conn, [row['user_id'] for row in rows])
        for summary, row in zip(summaries, rows):
            summary['userId'] = row['user_id']
            summary['userName'] = names.get(row['user_id'], '')
        return summaries

    def audit_trail(self, limit):
        with self.engine.connect() as conn:
            rows = conn.execute(select(s.audit_events.c.id, s.audit_events.c.action, s.audit_events.c.created_at,
                                       s.audit_events.c.entity_id, s.audit_events.c.details, s.audit_events.c.session_id,
                                       s.devices.c.user_id)
                                .select_from(s.audit_events.outerjoin(s.sessions, s.audit_events.c.session_id == s.sessions.c.id)
                                             .outerjoin(s.devices, s.sessions.c.device_id == s.devices.c.id))
                                .order_by(s.audit_events.c.created_at.desc()).limit(limit)).mappings().all()
            names = self._names(conn, [row['user_id'] for row in rows])
        return [{'id': row['id'], 'action': row['action'], 'at': row['created_at'], 'entityId': row['entity_id'],
                 'details': row['details'] or {}, 'sessionId': row['session_id'], 'userId': row['user_id'],
                 'userName': names.get(row['user_id'], '')} for row in rows]

    def trips(self, limit):
        now = s.Clock.now()
        with self.engine.connect() as conn:
            rows = conn.execute(select(s.trips).order_by(s.trips.c.created_at.desc()).limit(limit)).mappings().all()
            names = self._names(conn, [row['user_id'] for row in rows])
            result = SinglyLinkedList[dict]()
            for row in rows:
                try:
                    data = json.loads(self.vault.decrypt(row['encrypted_details']))
                except Exception:
                    data = {}
                result.append({'id': row['id'], 'userId': row['user_id'], 'userName': names.get(row['user_id'], ''),
                               'name': data.get('name', ''), 'pointA': data.get('pointA', ''), 'pointB': data.get('pointB', ''),
                               'vehicle': data.get('vehicle'), 'startedAt': row['created_at'], 'endedAt': row['ended_at'],
                               'durationMs': max(0, (row['ended_at'] or now) - row['created_at']),
                               **TripService.metrics(conn, row['id'])})
        return list(result)


StatusFilter = Literal['all', 'UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS', 'REPAIRED', 'REJECTED']


class AdminController:
    def __init__(self):
        self.router = APIRouter(prefix='/api/admin', dependencies=[Depends(SessionGuard.admin)])
        self.router.add_api_route('/overview', self.overview, methods=['GET'])
        self.router.add_api_route('/users', self.users, methods=['GET'])
        self.router.add_api_route('/users/{user_id}/role', self.change_role, methods=['POST'])
        self.router.add_api_route('/users/{user_id}/active', self.change_active, methods=['POST'])
        self.router.add_api_route('/reports', self.reports, methods=['GET'])
        self.router.add_api_route('/reports/{report_id}/status', self.change_status, methods=['POST'])
        self.router.add_api_route('/sessions', self.sessions, methods=['GET'])
        self.router.add_api_route('/audit', self.audit, methods=['GET'])
        self.router.add_api_route('/trips', self.trips, methods=['GET'])

    @staticmethod
    def _service(request: Request) -> AdminService:
        return request.app.state.admin

    def overview(self, request: Request):
        return self._service(request).overview()

    def users(self, request: Request, limit: int = Query(200, ge=1, le=500)):
        return {'users': self._service(request).users(limit)}

    def change_role(self, user_id: UUID, payload: RoleChange, request: Request, admin=Depends(SessionGuard.admin)):
        return self._service(request).change_role(str(user_id), payload.role, admin)

    def change_active(self, user_id: UUID, payload: ActiveChange, request: Request, admin=Depends(SessionGuard.admin)):
        return self._service(request).change_active(str(user_id), payload.active, admin)

    def reports(self, request: Request, status: StatusFilter = 'all', limit: int = Query(100, ge=1, le=200),
                offset: int = Query(0, ge=0)):
        return self._service(request).reports(status, limit, offset)

    def change_status(self, report_id: UUID, payload: StatusChange, request: Request, admin=Depends(SessionGuard.admin)):
        return self._service(request).change_status(str(report_id), payload, admin)

    def sessions(self, request: Request, limit: int = Query(100, ge=1, le=300)):
        return {'sessions': self._service(request).sessions(limit)}

    def audit(self, request: Request, limit: int = Query(150, ge=1, le=500)):
        return {'events': self._service(request).audit_trail(limit)}

    def trips(self, request: Request, limit: int = Query(100, ge=1, le=300)):
        return {'trips': self._service(request).trips(limit)}
