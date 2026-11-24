"""Review and merge duplicated pothole reports (Operator and Administrator roles)."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text, update
from .auth import AuditLog
from .duplicates import DuplicateDetector
from .maintenance import StatusWorkflow
from .operator_api import field_staff
from .geo import GeoMath
from . import schema as s

MAX_MERGE_METERS = 50
MERGE_LOCK = 771012  # Same lock as new scans, so no report is matched to a pothole being merged.


class MergeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    canonicalReportId: UUID
    duplicateReportIds: list[UUID] = Field(min_length=1, max_length=50)

    @field_validator('duplicateReportIds')
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Repeated report')
        return value


class DuplicateService:
    def __init__(self, request: Request):
        self.app = request.app
        self.repo = request.app.state.repo

    def review(self, radius: float) -> dict:
        reports, _ = self.repo.list_reports(5000, 0, statuses=list(StatusWorkflow.OPEN_STATUSES))
        detector = DuplicateDetector(reports, radius)
        return {'clusters': [cluster.as_dict() for cluster in detector.clusters()], 'stats': detector.stats(),
                'generatedAt': s.Clock.now()}

    def _load(self, conn, report_ids: list[str]) -> dict[str, dict]:
        rows = conn.execute(select(s.reports.c.id, s.potholes.c.id.label('pothole_id'), s.potholes.c.status,
                                   s.potholes.c.lat, s.potholes.c.lng)
                            .select_from(s.reports.join(s.potholes, s.reports.c.pothole_id == s.potholes.c.id))
                            .where(s.reports.c.id.in_(report_ids))
                            .with_for_update(of=s.potholes)).mappings().all()
        return {row['id']: dict(row) for row in rows}

    def merge(self, payload: MergeRequest, session: dict) -> dict:
        canonical_id = str(payload.canonicalReportId)
        duplicate_ids = [str(identity) for identity in payload.duplicateReportIds]
        if canonical_id in duplicate_ids:
            raise HTTPException(422, 'El reporte principal no puede ser también un duplicado.')
        with self.app.state.engine.begin() as conn:
            conn.execute(text(f'SELECT pg_advisory_xact_lock({MERGE_LOCK})'))
            rows = self._load(conn, [canonical_id, *duplicate_ids])
            if len(rows) != 1 + len(duplicate_ids):
                raise HTTPException(404, 'Algún reporte ya no existe.')
            canonical = rows[canonical_id]
            duplicates = [rows[identity] for identity in duplicate_ids]
            if any(row['status'] not in StatusWorkflow.OPEN_STATUSES for row in rows.values()):
                raise HTTPException(409, 'Solo se fusionan baches abiertos.')
            if any(row['pothole_id'] == canonical['pothole_id'] for row in duplicates) or \
                    len({row['pothole_id'] for row in duplicates}) != len(duplicates):
                raise HTTPException(409, 'Los reportes ya pertenecen al mismo bache.')
            if any(GeoMath.distance(canonical, row) > MAX_MERGE_METERS for row in duplicates):
                raise HTTPException(409, f'Solo se fusionan reportes a menos de {MAX_MERGE_METERS} m del principal.')
            moved = 0
            for row in duplicates:
                # Passes now count for the surviving pothole, so exposure is not split.
                moved += conn.execute(update(s.pothole_passes).where(s.pothole_passes.c.pothole_id == row['pothole_id'])
                                      .values(pothole_id=canonical['pothole_id'])).rowcount
                conn.execute(update(s.potholes).where(s.potholes.c.id == row['pothole_id']).values(status='REJECTED'))
                conn.execute(s.status_events.insert().values(
                    pothole_id=row['pothole_id'], actor_id=session['user_id'], old_status=row['status'],
                    new_status='REJECTED', reason=f'Duplicado del reporte {canonical_id}'))
            AuditLog.record(conn, session['id'], 'operator.duplicates.merged', canonical_id,
                  {'duplicates': len(duplicates), 'passesMoved': moved})
        return {'report': self.repo.get_report(canonical_id), 'merged': len(duplicates), 'passesMoved': moved}


class DuplicatesController:
    """Routes to review and merge duplicates; only operators and administrators reach them."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/operator/duplicates', dependencies=[Depends(field_staff)])
        self.router.add_api_route('', self.review_duplicates, methods=['GET'])
        self.router.add_api_route('/merge', self.merge_duplicates, methods=['POST'])

    def review_duplicates(self, request: Request,
                          radius: float = Query(15, ge=DuplicateDetector.MIN_RADIUS, le=DuplicateDetector.MAX_RADIUS)):
        return DuplicateService(request).review(radius)

    def merge_duplicates(self, payload: MergeRequest, request: Request, session=Depends(field_staff)):
        return DuplicateService(request).merge(payload, session)
