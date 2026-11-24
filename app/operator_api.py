"""Operator workspace: prioritized work queue, day route and status workflow.

The heap and the route are rebuilt from PostgreSQL on every request. Nothing is
kept in process memory, so every replica of the API returns the same answer.
"""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from .auth import Roles, SessionGuard
from .contracts import Position
from .demo_policy import forbid_demo_writes
from .maintenance import MaintenanceQueue, StatusWorkflow
from .maintenance_commands import ChangeStatusCommand, CommandExecutor, MaintenanceRepository
from .profile import AccountFormat
from .route_planning import RoutePlannerFactory
from . import schema as s

FIELD_ROLES = (Roles.OPERATOR, Roles.ADMIN)
# One shared callable so FastAPI resolves the role check once per request.
field_staff = SessionGuard.require_roles(*FIELD_ROLES)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['CONFIRMED', 'IN_PROGRESS', 'REPAIRED', 'REJECTED']
    reason: str = Field(default='', max_length=280)


class MaintenanceService:
    """Facade: one entry point for the router over the queue, the planner and the commands."""

    MAX_REPORTS = 2000

    def __init__(self, request: Request):
        self.app = request.app
        self.repo = request.app.state.repo
        self.workflow = StatusWorkflow()

    def open_reports(self) -> list[dict]:
        reports, _ = self.repo.list_reports(self.MAX_REPORTS, 0, statuses=list(StatusWorkflow.OPEN_STATUSES))
        return reports

    def queue(self, limit: int) -> dict:
        now = s.Clock.now()
        work = MaintenanceQueue(self.open_reports(), now)
        items = [{'rank': rank, 'report': report, 'priority': breakdown.as_dict(),
                  'allowedTransitions': self.workflow.allowed(report['status'])}
                 for rank, (report, breakdown) in enumerate(work.top(limit), 1)]
        return {'items': items, 'total': len(work), 'generatedAt': now,
                'structure': {'name': 'indexed-binary-max-heap', 'size': len(work.heap),
                              'height': work.heap.height, 'heapifyComparisons': work.heap.comparisons}}

    def plan(self, limit: int, start: dict | None, algorithm: str = RoutePlannerFactory.DEFAULT) -> dict:
        now = s.Clock.now()
        selected = MaintenanceQueue(self.open_reports(), now).top(limit)
        stops = [report for report, _ in selected]
        route = RoutePlannerFactory.create(algorithm, start, stops).plan()
        scores = {report['id']: breakdown.score for report, breakdown in selected}
        ordered = [{'step': step, 'report': stops[index], 'priorityScore': scores[stops[index]['id']],
                    'legMeters': leg}
                   for step, (index, leg) in enumerate(zip(route['order'], route['legsMeters']), 1)]
        return {'start': start, 'stops': ordered, 'totalMeters': route['totalMeters'],
                'priorityOrderMeters': route['priorityOrderMeters'], 'savedPercent': route['savedPercent'],
                'improvements': route['improvements'], 'generatedAt': now,
                'algorithm': route['algorithm'], 'algorithms': RoutePlannerFactory.names()}

    def transition(self, report_id: str, payload: TransitionRequest, session: dict) -> dict:
        command = ChangeStatusCommand(report_id, payload.status, payload.reason, self.workflow)
        CommandExecutor(self.app.state.engine).run(command, session)
        report = self.repo.get_report(report_id)
        return {'report': report, 'allowedTransitions': self.workflow.allowed(report['status'])}

    def timeline(self, report_id: str) -> dict:
        vault = self.app.state.vault
        with self.app.state.engine.connect() as conn:
            rows = MaintenanceRepository(conn).status_history(report_id)
        if rows is None:
            raise HTTPException(404, 'El reporte no existe.')
        return {'events': [{'id': row['id'], 'at': row['created_at'], 'from': row['old_status'], 'to': row['new_status'],
                            'reason': row['reason'],
                            'actorName': AccountFormat.decrypt(vault, row['display_name']) if row['display_name'] else 'Sistema'}
                           for row in rows]}


class OperatorController:
    """Routes of the maintenance workspace; only operators and administrators reach them."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/operator', dependencies=[Depends(field_staff)])
        self.router.add_api_route('/queue', self.work_queue, methods=['GET'])
        self.router.add_api_route('/plan', self.day_plan, methods=['GET'])
        self.router.add_api_route('/reports/{report_id}/transition', self.change_status, methods=['POST'])
        self.router.add_api_route('/reports/{report_id}/timeline', self.status_timeline, methods=['GET'])

    def work_queue(self, request: Request, limit: int = Query(20, ge=1, le=100)):
        return MaintenanceService(request).queue(limit)

    def day_plan(self, request: Request, limit: int = Query(8, ge=1, le=25),
                 lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180),
                 algorithm: Literal['two-opt', 'nearest-neighbour', 'priority'] = 'two-opt'):
        if (lat is None) != (lng is None):
            raise HTTPException(422, 'Envía latitud y longitud juntas o ninguna.')
        start = Position(lat=lat, lng=lng, accuracy=0).model_dump(include={'lat', 'lng'}) if lat is not None else None
        return MaintenanceService(request).plan(limit, start, algorithm)

    def change_status(self, report_id: UUID, payload: TransitionRequest, request: Request,
                      session=Depends(field_staff), _writer=Depends(forbid_demo_writes)):
        return MaintenanceService(request).transition(str(report_id), payload, session)

    def status_timeline(self, report_id: UUID, request: Request):
        return MaintenanceService(request).timeline(str(report_id))
