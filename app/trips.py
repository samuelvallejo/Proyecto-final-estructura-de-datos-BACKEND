import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, func, update
from sqlalchemy.dialects.postgresql import insert
from .auth import current_session, FAILURE
from .contracts import Position
from .repository import distance
from . import schema as s


class TripCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2, max_length=80)
    pointA: str = Field(min_length=2, max_length=120)
    pointB: str = Field(min_length=2, max_length=120)
    position: Position

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


def owned_trip(conn, trip_id, user_id, active=False, lock=False):
    query = select(s.trips).where(s.trips.c.id == str(trip_id), s.trips.c.user_id == user_id)
    row = conn.execute(query.with_for_update() if lock else query).mappings().first()
    if not row:
        raise HTTPException(404, 'No se pudo completar la operación.')
    if active and row['ended_at'] is not None:
        raise HTTPException(409, 'El recorrido ya terminó.')
    return row


def owner_for_session(conn, session_id):
    return conn.execute(select(s.devices.c.user_id).select_from(s.sessions.join(s.devices))
                        .where(s.sessions.c.id == session_id)).scalar_one()


def validate_scan_trip(engine, trip_id, session_id):
    with engine.connect() as conn:
        owned_trip(conn, trip_id, owner_for_session(conn, session_id), active=True)


def link_reports(engine, trip_id, session_id, reports):
    with engine.begin() as conn:
        owned_trip(conn, trip_id, owner_for_session(conn, session_id), lock=True)
        for report in reports:
            conn.execute(insert(s.trip_reports).values(trip_id=trip_id, report_id=report['id'])
                         .on_conflict_do_nothing(index_elements=['trip_id', 'report_id']))


def serialize(request, conn, row, details=False):
    data = json.loads(request.app.state.vault.decrypt(row['encrypted_details']))
    report_count = conn.execute(select(func.count()).select_from(s.trip_reports)
                               .where(s.trip_reports.c.trip_id == row['id'])).scalar_one()
    result = {**data, 'id': row['id'], 'startedAt': row['created_at'], 'endedAt': row['ended_at'], 'reportCount': report_count}
    if details:
        samples = conn.execute(select(s.trip_samples.c.encrypted_position).where(s.trip_samples.c.trip_id == row['id'])
                              .order_by(s.trip_samples.c.created_at, s.trip_samples.c.id).limit(10000)).scalars().all()
        result['path'] = [json.loads(request.app.state.vault.decrypt(point)) for point in samples]
        rows = conn.execute(request.app.state.repo.query().join(s.trip_reports, s.trip_reports.c.report_id == s.reports.c.id)
                            .where(s.trip_reports.c.trip_id == row['id']).order_by(s.reports.c.created_at)).mappings().all()
        result['reports'] = [request.app.state.repo.serialize(report) for report in rows]
    return result


router = APIRouter(prefix='/api/trips')


@router.get('')
def list_trips(request: Request, session=Depends(current_session)):
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(select(s.trips).where(s.trips.c.user_id == session['user_id'])
                            .order_by(s.trips.c.created_at.desc()).limit(100)).mappings().all()
        return {'trips': [serialize(request, conn, row) for row in rows]}


@router.post('', status_code=201)
def create_trip(payload: TripCreate, request: Request, session=Depends(current_session)):
    vault = request.app.state.vault
    with request.app.state.engine.begin() as conn:
        conn.execute(text_lock())
        active = conn.execute(select(s.trips.c.id).where(s.trips.c.user_id == session['user_id'], s.trips.c.ended_at.is_(None))).first()
        if active:
            raise HTTPException(409, 'Finaliza el recorrido activo antes de crear otro.')
        data = {**payload.model_dump(exclude={'position'}), 'start': payload.position.model_dump(), 'end': None}
        row = conn.execute(s.trips.insert().values(user_id=session['user_id'], session_id=session['id'],
                           encrypted_details=vault.encrypt(json.dumps(data))).returning(s.trips)).mappings().one()
        conn.execute(s.trip_samples.insert().values(trip_id=row['id'], encrypted_position=vault.encrypt(json.dumps(payload.position.model_dump()))))
        return serialize(request, conn, row, details=True)


def text_lock():
    from sqlalchemy import text
    return text('SELECT pg_advisory_xact_lock(771015)')


@router.get('/{trip_id}')
def get_trip(trip_id: UUID, request: Request, session=Depends(current_session)):
    with request.app.state.engine.connect() as conn:
        return serialize(request, conn, owned_trip(conn, trip_id, session['user_id']), details=True)


@router.post('/{trip_id}/samples')
def save_sample(trip_id: UUID, payload: Sample, request: Request, session=Depends(current_session)):
    vault = request.app.state.vault
    with request.app.state.engine.begin() as conn:
        owned_trip(conn, trip_id, session['user_id'], active=True, lock=True)
        count = conn.execute(select(func.count()).select_from(s.trip_samples).where(s.trip_samples.c.trip_id == str(trip_id))).scalar_one()
        if count >= 10000:
            raise HTTPException(429, 'Se alcanzó el límite del recorrido. Finalízalo para empezar otro.')
        previous = conn.execute(select(s.trip_samples).where(s.trip_samples.c.trip_id == str(trip_id))
                                .order_by(s.trip_samples.c.created_at.desc()).limit(1)).mappings().first()
        if previous and (s.now() - previous['created_at'] < 2000 or distance(json.loads(vault.decrypt(previous['encrypted_position'])), payload.position.model_dump()) < 5):
            return {'message': 'Todo se ejecutó correctamente.'}
        conn.execute(s.trip_samples.insert().values(trip_id=str(trip_id), encrypted_position=vault.encrypt(json.dumps(payload.position.model_dump()))))
    return {'message': 'Todo se ejecutó correctamente.'}


@router.post('/{trip_id}/finish')
def finish_trip(trip_id: UUID, payload: Finish, request: Request, session=Depends(current_session)):
    vault = request.app.state.vault
    with request.app.state.engine.begin() as conn:
        row = owned_trip(conn, trip_id, session['user_id'], lock=True)
        if row['ended_at'] is not None:
            return serialize(request, conn, row, details=True)
        data = json.loads(vault.decrypt(row['encrypted_details']))
        last = conn.execute(select(s.trip_samples.c.encrypted_position).where(s.trip_samples.c.trip_id == str(trip_id))
                            .order_by(s.trip_samples.c.created_at.desc()).limit(1)).scalar_one()
        end = payload.position.model_dump() if payload.position else json.loads(vault.decrypt(last))
        data['end'] = end
        conn.execute(s.trip_samples.insert().values(trip_id=str(trip_id), encrypted_position=vault.encrypt(json.dumps(end))))
        updated = conn.execute(update(s.trips).where(s.trips.c.id == str(trip_id)).values(ended_at=s.now(),
                               encrypted_details=vault.encrypt(json.dumps(data))).returning(s.trips)).mappings().one()
        return serialize(request, conn, updated, details=True)
