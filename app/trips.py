"""Trips and driving sessions: encrypted GPS paths owned by one account."""
import json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from . import schema as s
from .auth import AuditLog, SessionGuard
from .contracts import Position
from .geo import GeoMath
from .repository import PassTracker
from .structures import HashSet

DONE = 'Todo se ejecutó correctamente.'


class TripCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2, max_length=80)
    pointA: str = Field(min_length=2, max_length=120)
    pointB: str = Field(min_length=2, max_length=120)
    position: Position
    # Driving session: vehicle used during the automatic scan.
    vehicle: Literal['moto', 'carro'] | None = None

    @field_validator('name', 'pointA', 'pointB')
    @classmethod
    def safe_label(cls, value):
        value = value.strip()
        if len(value) < 2 or any(ord(c) < 32 for c in value):
            raise ValueError('invalid')
        return value


class Sample(BaseModel):
    model_config = ConfigDict(extra='forbid')
    position: Position


class Finish(BaseModel):
    model_config = ConfigDict(extra='forbid')
    position: Position | None = None


class TripService:
    MAX_SAMPLES = 10_000
    MIN_SAMPLE_INTERVAL_MS = 2_000
    MIN_SAMPLE_DISTANCE_M = 5
    PASS_MAX_ACCURACY_M = 50

    def __init__(self, engine, vault, repository, settings):
        self.engine, self.vault, self.repository, self.settings = engine, vault, repository, settings

    @staticmethod
    def owned(conn, trip_id, user_id, active=False, lock=False):
        """Trip row owned by ``user_id``; 404 otherwise and 409 if ``active`` and already finished."""
        query = select(s.trips).where(s.trips.c.id == str(trip_id), s.trips.c.user_id == user_id)
        row = conn.execute(query.with_for_update() if lock else query).mappings().first()
        if not row:
            raise HTTPException(404, 'No se pudo completar la operación.')
        if active and row['ended_at'] is not None:
            raise HTTPException(409, 'El recorrido ya terminó.')
        return row

    @staticmethod
    def owner_of_session(conn, session_id):
        return conn.execute(select(s.devices.c.user_id).select_from(s.sessions.join(s.devices))
                            .where(s.sessions.c.id == session_id)).scalar_one()

    @staticmethod
    def metrics(conn, trip_id):
        """Reports linked to the trip, known potholes passed and distinct potholes on the way."""
        report_count = conn.execute(select(func.count()).select_from(s.trip_reports)
                                   .where(s.trip_reports.c.trip_id == trip_id)).scalar_one()
        potholes = HashSet(conn.execute(select(s.reports.c.pothole_id).select_from(s.trip_reports.join(s.reports))
                                        .where(s.trip_reports.c.trip_id == trip_id)).scalars())
        passed = HashSet(conn.execute(select(s.pothole_passes.c.pothole_id)
                                      .where(s.pothole_passes.c.trip_id == trip_id)).scalars())
        for pothole in passed:
            potholes.add(pothole)
        return {'reportCount': report_count, 'passCount': len(passed), 'potholeCount': len(potholes)}

    @staticmethod
    def path_length(points):
        total, previous = 0.0, None
        for point in points:
            if previous is not None:
                total += GeoMath.distance(previous, point)
            previous = point
        return round(total)

    def _encrypt(self, value):
        return self.vault.encrypt(json.dumps(value))

    def _decrypt(self, value):
        return json.loads(self.vault.decrypt(value))

    def serialize(self, conn, row, details=False):
        data = self._decrypt(row['encrypted_details'])
        finished = row['ended_at'] or s.Clock.now()
        result = {**data, 'id': row['id'], 'startedAt': row['created_at'], 'endedAt': row['ended_at'],
                  'durationMs': max(0, finished - row['created_at']), **self.metrics(conn, row['id'])}
        result.setdefault('vehicle', None)
        if details:
            samples = conn.execute(select(s.trip_samples.c.encrypted_position).where(s.trip_samples.c.trip_id == row['id'])
                                  .order_by(s.trip_samples.c.created_at, s.trip_samples.c.id).limit(self.MAX_SAMPLES)).scalars().all()
            result['path'] = [self._decrypt(point) for point in samples]
            result['distanceMeters'] = self.path_length(result['path'])
            rows = conn.execute(self.repository.query().join(s.trip_reports, s.trip_reports.c.report_id == s.reports.c.id)
                                .where(s.trip_reports.c.trip_id == row['id']).order_by(s.reports.c.created_at)).mappings().all()
            result['reports'] = [self.repository.serialize(report) for report in rows]
        return result

    def validate_for_scan(self, trip_id, session_id):
        with self.engine.connect() as conn:
            self.owned(conn, trip_id, self.owner_of_session(conn, session_id), active=True)

    def link_reports(self, trip_id, session_id, reports):
        with self.engine.begin() as conn:
            self.owned(conn, trip_id, self.owner_of_session(conn, session_id), lock=True)
            for report in reports:
                conn.execute(insert(s.trip_reports).values(trip_id=trip_id, report_id=report['id'])
                             .on_conflict_do_nothing(index_elements=['trip_id', 'report_id']))

    def list(self, session):
        with self.engine.connect() as conn:
            rows = conn.execute(select(s.trips).where(s.trips.c.user_id == session['user_id'])
                                .order_by(s.trips.c.created_at.desc()).limit(100)).mappings().all()
            return [self.serialize(conn, row) for row in rows]

    def create(self, payload: TripCreate, session):
        with self.engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(771015)'))
            active = conn.execute(select(s.trips.c.id).where(s.trips.c.user_id == session['user_id'],
                                                             s.trips.c.ended_at.is_(None))).first()
            if active:
                raise HTTPException(409, 'Finaliza el recorrido activo antes de crear otro.')
            data = {**payload.model_dump(exclude={'position'}), 'start': payload.position.model_dump(), 'end': None}
            row = conn.execute(s.trips.insert().values(user_id=session['user_id'], session_id=session['id'],
                               encrypted_details=self._encrypt(data)).returning(s.trips)).mappings().one()
            conn.execute(s.trip_samples.insert().values(trip_id=row['id'], encrypted_position=self._encrypt(payload.position.model_dump())))
            AuditLog.record(conn, session['id'], 'trip.started', row['id'], {'vehicle': payload.vehicle})
            return self.serialize(conn, row, details=True)

    def get(self, trip_id, session):
        with self.engine.connect() as conn:
            return self.serialize(conn, self.owned(conn, trip_id, session['user_id']), details=True)

    def add_sample(self, trip_id, position: Position, session):
        """Store a GPS sample (skipping near-duplicates) and record passes near known potholes."""
        with self.engine.begin() as conn:
            self.owned(conn, trip_id, session['user_id'], active=True, lock=True)
            count = conn.execute(select(func.count()).select_from(s.trip_samples)
                                 .where(s.trip_samples.c.trip_id == str(trip_id))).scalar_one()
            if count >= self.MAX_SAMPLES:
                raise HTTPException(429, 'Se alcanzó el límite del recorrido. Finalízalo para empezar otro.')
            point = position.model_dump()
            passed = PassTracker.record(conn, session['user_id'], session['id'],
                                        PassTracker.nearby(conn, point, self.settings.pass_radius_meters),
                                        'trip', str(trip_id)) if point['accuracy'] <= self.PASS_MAX_ACCURACY_M else []
            previous = conn.execute(select(s.trip_samples).where(s.trip_samples.c.trip_id == str(trip_id))
                                    .order_by(s.trip_samples.c.created_at.desc()).limit(1)).mappings().first()
            too_close = previous and (s.Clock.now() - previous['created_at'] < self.MIN_SAMPLE_INTERVAL_MS
                                      or GeoMath.distance(self._decrypt(previous['encrypted_position']), point) < self.MIN_SAMPLE_DISTANCE_M)
            if not too_close:
                conn.execute(s.trip_samples.insert().values(trip_id=str(trip_id), encrypted_position=self._encrypt(point)))
        return {'message': DONE, 'passed': len(passed)}

    def finish(self, trip_id, position: Position | None, session):
        with self.engine.begin() as conn:
            row = self.owned(conn, trip_id, session['user_id'], lock=True)
            if row['ended_at'] is not None:
                return self.serialize(conn, row, details=True)
            data = self._decrypt(row['encrypted_details'])
            last = conn.execute(select(s.trip_samples.c.encrypted_position).where(s.trip_samples.c.trip_id == str(trip_id))
                                .order_by(s.trip_samples.c.created_at.desc()).limit(1)).scalar_one()
            end = position.model_dump() if position else self._decrypt(last)
            data['end'] = end
            conn.execute(s.trip_samples.insert().values(trip_id=str(trip_id), encrypted_position=self._encrypt(end)))
            updated = conn.execute(update(s.trips).where(s.trips.c.id == str(trip_id)).values(
                ended_at=s.Clock.now(), encrypted_details=self._encrypt(data)).returning(s.trips)).mappings().one()
            result = self.serialize(conn, updated, details=True)
            AuditLog.record(conn, session['id'], 'trip.finished', str(trip_id), {
                'durationMs': result['durationMs'], 'potholes': result['potholeCount'], 'distanceMeters': result['distanceMeters']})
            return result


class TripController:
    def __init__(self):
        self.router = APIRouter(prefix='/api/trips')
        self.router.add_api_route('', self.list_trips, methods=['GET'])
        self.router.add_api_route('', self.create_trip, methods=['POST'], status_code=201)
        self.router.add_api_route('/{trip_id}', self.get_trip, methods=['GET'])
        self.router.add_api_route('/{trip_id}/samples', self.save_sample, methods=['POST'])
        self.router.add_api_route('/{trip_id}/finish', self.finish_trip, methods=['POST'])

    @staticmethod
    def _service(request: Request) -> TripService:
        return request.app.state.trips

    def list_trips(self, request: Request, session=Depends(SessionGuard.current)):
        return {'trips': self._service(request).list(session)}

    def create_trip(self, payload: TripCreate, request: Request, session=Depends(SessionGuard.current)):
        return self._service(request).create(payload, session)

    def get_trip(self, trip_id: UUID, request: Request, session=Depends(SessionGuard.current)):
        return self._service(request).get(trip_id, session)

    def save_sample(self, trip_id: UUID, payload: Sample, request: Request, session=Depends(SessionGuard.current)):
        return self._service(request).add_sample(trip_id, payload.position, session)

    def finish_trip(self, trip_id: UUID, payload: Finish, request: Request, session=Depends(SessionGuard.current)):
        return self._service(request).finish(trip_id, payload.position, session)
