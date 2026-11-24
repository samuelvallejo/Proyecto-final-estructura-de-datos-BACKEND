"""Review and merge duplicated pothole reports (Operator and Administrator roles)."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .demo_policy import forbid_demo_writes
from .duplicates import DuplicateDetector
from .maintenance import StatusWorkflow
from .maintenance_commands import CommandExecutor, MergeDuplicatesCommand
from .operator_api import field_staff
from . import schema as s


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
    """Facade over the detector (reads) and the merge command (writes)."""

    def __init__(self, request: Request):
        self.app = request.app
        self.repo = request.app.state.repo

    def review(self, radius: float, method: str = 'grid') -> dict:
        reports, _ = self.repo.list_reports(5000, 0, statuses=list(StatusWorkflow.OPEN_STATUSES))
        detector = DuplicateDetector(reports, radius, method)
        return {'clusters': [cluster.as_dict() for cluster in detector.clusters()], 'stats': detector.stats(),
                'generatedAt': s.Clock.now()}

    def merge(self, payload: MergeRequest, session: dict) -> dict:
        command = MergeDuplicatesCommand(str(payload.canonicalReportId), [str(identity) for identity in payload.duplicateReportIds])
        details = CommandExecutor(self.app.state.engine).run(command, session)
        return {'report': self.repo.get_report(command.canonical_id), 'merged': details['duplicates'],
                'passesMoved': details['passesMoved']}


class DuplicatesController:
    """Routes to review and merge duplicates; only operators and administrators reach them."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/operator/duplicates', dependencies=[Depends(field_staff)])
        self.router.add_api_route('', self.review_duplicates, methods=['GET'])
        self.router.add_api_route('/merge', self.merge_duplicates, methods=['POST'])

    def review_duplicates(self, request: Request,
                          radius: float = Query(15, ge=DuplicateDetector.MIN_RADIUS, le=DuplicateDetector.MAX_RADIUS),
                          method: Literal['grid', 'brute-force'] = 'grid'):
        return DuplicateService(request).review(radius, method)

    def merge_duplicates(self, payload: MergeRequest, request: Request, session=Depends(field_staff),
                         _writer=Depends(forbid_demo_writes)):
        return DuplicateService(request).merge(payload, session)
