"""Write operations of the maintenance workspace.

Design patterns
* Repository: ``MaintenanceRepository`` hides the SQL of potholes, status
  events and passes behind intention-revealing methods.
* Chain of Responsibility: ``ValidationRule`` objects are linked; each one
  checks one condition and passes the request to the next rule.
* Template Method: ``ValidationRule.handle`` fixes the algorithm (check,
  reject or delegate) and subclasses only implement ``violated``.
* Command: each write (``ChangeStatusCommand``, ``MergeDuplicatesCommand``) is
  an object that knows which reports it needs, its rules and how to apply itself.
* Invoker: ``CommandExecutor`` runs any command the same way: one transaction,
  optional advisory lock, row locks, validation chain, change and audit entry.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import select, text, update
from .auth import AuditLog
from .maintenance import StatusWorkflow
from .geo import GeoMath
from . import schema as s

NEW_SCAN_LOCK = 771012  # Same advisory lock as save_scan: no scan matches a pothole being merged.


class MaintenanceRepository:
    """Repository: data access for maintenance writes inside one connection."""

    def __init__(self, conn):
        self.conn = conn

    def advisory_lock(self, key: int) -> None:
        self.conn.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})

    def lock_reports(self, report_ids: list[str]) -> dict[str, dict]:
        """Report id -> its pothole (id, status, position), locking the pothole rows."""
        rows = self.conn.execute(select(s.reports.c.id, s.potholes.c.id.label('pothole_id'), s.potholes.c.status,
                                        s.potholes.c.lat, s.potholes.c.lng)
                                 .select_from(s.reports.join(s.potholes, s.reports.c.pothole_id == s.potholes.c.id))
                                 .where(s.reports.c.id.in_(report_ids))
                                 .with_for_update(of=s.potholes)).mappings().all()
        return {row['id']: dict(row) for row in rows}

    def change_status(self, pothole: dict, status: str, actor_id: str, reason: str) -> None:
        self.conn.execute(update(s.potholes).where(s.potholes.c.id == pothole['pothole_id']).values(status=status))
        self.conn.execute(s.status_events.insert().values(pothole_id=pothole['pothole_id'], actor_id=actor_id,
                                                          old_status=pothole['status'], new_status=status, reason=reason))

    def move_passes(self, from_pothole: str, to_pothole: str) -> int:
        return self.conn.execute(update(s.pothole_passes).where(s.pothole_passes.c.pothole_id == from_pothole)
                                 .values(pothole_id=to_pothole)).rowcount

    def status_history(self, report_id: str) -> list[dict] | None:
        """Status events of the report's pothole, oldest first; None if the report does not exist."""
        pothole_id = self.conn.execute(select(s.reports.c.pothole_id).where(s.reports.c.id == report_id)).scalar_one_or_none()
        if pothole_id is None:
            return None
        return [dict(row) for row in self.conn.execute(
            select(s.status_events.c.id, s.status_events.c.created_at, s.status_events.c.old_status,
                   s.status_events.c.new_status, s.status_events.c.reason, s.users.c.display_name)
            .select_from(s.status_events.outerjoin(s.users, s.status_events.c.actor_id == s.users.c.id))
            .where(s.status_events.c.pothole_id == pothole_id)
            .order_by(s.status_events.c.created_at, s.status_events.c.id)).mappings().all()]


@dataclass
class ValidationContext:
    command: 'MaintenanceCommand'
    rows: dict[str, dict]


class ValidationRule(ABC):
    """Chain of Responsibility link; ``handle`` is the Template Method."""

    status_code = 409
    message = ''

    def __init__(self):
        self.next_rule: ValidationRule | None = None

    def then(self, rule: 'ValidationRule') -> 'ValidationRule':
        """Link ``rule`` after this one and return it, so chains read left to right."""
        self.next_rule = rule
        return rule

    def handle(self, context: ValidationContext) -> None:
        if self.violated(context):
            raise HTTPException(self.status_code, self.message)
        if self.next_rule is not None:
            self.next_rule.handle(context)

    @abstractmethod
    def violated(self, context: ValidationContext) -> bool: ...


def chain(*rules: ValidationRule) -> ValidationRule:
    for current, following in zip(rules, rules[1:]):
        current.then(following)
    return rules[0]


class ReportsExistRule(ValidationRule):
    status_code = 404

    def __init__(self, message: str = 'El reporte no existe.'):
        super().__init__()
        self.message = message

    def violated(self, context):
        return any(identity not in context.rows for identity in context.command.report_ids())


class OpenStatusRule(ValidationRule):
    message = 'Solo se fusionan baches abiertos.'

    def violated(self, context):
        return any(row['status'] not in StatusWorkflow.OPEN_STATUSES for row in context.rows.values())


class AllowedTransitionRule(ValidationRule):
    message = 'Ese cambio de estado no está permitido desde el estado actual.'

    def __init__(self, workflow: StatusWorkflow):
        super().__init__()
        self.workflow = workflow

    def violated(self, context):
        command = context.command
        return not self.workflow.can_move(context.rows[command.report_id]['status'], command.target)


class DistinctPotholesRule(ValidationRule):
    message = 'Los reportes ya pertenecen al mismo bache.'

    def violated(self, context):
        potholes = [context.rows[identity]['pothole_id'] for identity in context.command.report_ids()]
        return len(set(potholes)) != len(potholes)


class MaxDistanceRule(ValidationRule):
    def __init__(self, meters: float):
        super().__init__()
        self.meters = meters
        self.message = f'Solo se fusionan reportes a menos de {meters:g} m del principal.'

    def violated(self, context):
        command = context.command
        canonical = context.rows[command.canonical_id]
        return any(GeoMath.distance(canonical, context.rows[identity]) > self.meters for identity in command.duplicate_ids)


class MaintenanceCommand(ABC):
    """Command: a write on potholes with its own rules and audit entry."""

    action = ''
    lock_key: int | None = None

    @property
    @abstractmethod
    def entity_id(self) -> str: ...

    @abstractmethod
    def report_ids(self) -> list[str]: ...

    @abstractmethod
    def rules(self) -> ValidationRule: ...

    @abstractmethod
    def apply(self, repo: MaintenanceRepository, rows: dict[str, dict], actor_id: str) -> dict:
        """Perform the change; returns the details stored in the audit trail."""


class ChangeStatusCommand(MaintenanceCommand):
    action = 'operator.report.status'

    def __init__(self, report_id: str, target: str, reason: str = '', workflow: StatusWorkflow | None = None):
        self.report_id, self.target = report_id, target
        self.reason = reason.strip() or 'Cambio registrado por operación'
        self.workflow = workflow or StatusWorkflow()

    @property
    def entity_id(self) -> str:
        return self.report_id

    def report_ids(self) -> list[str]:
        return [self.report_id]

    def rules(self) -> ValidationRule:
        return chain(ReportsExistRule(), AllowedTransitionRule(self.workflow))

    def apply(self, repo, rows, actor_id):
        pothole = rows[self.report_id]
        repo.change_status(pothole, self.target, actor_id, self.reason)
        return {'from': pothole['status'], 'to': self.target}


class MergeDuplicatesCommand(MaintenanceCommand):
    action = 'operator.duplicates.merged'
    lock_key = NEW_SCAN_LOCK
    MAX_METERS = 50

    def __init__(self, canonical_id: str, duplicate_ids: list[str]):
        if canonical_id in duplicate_ids:
            raise HTTPException(422, 'El reporte principal no puede ser también un duplicado.')
        self.canonical_id, self.duplicate_ids = canonical_id, duplicate_ids

    @property
    def entity_id(self) -> str:
        return self.canonical_id

    def report_ids(self) -> list[str]:
        return [self.canonical_id, *self.duplicate_ids]

    def rules(self) -> ValidationRule:
        return chain(ReportsExistRule('Algún reporte ya no existe.'), OpenStatusRule(), DistinctPotholesRule(),
                     MaxDistanceRule(self.MAX_METERS))

    def apply(self, repo, rows, actor_id):
        canonical = rows[self.canonical_id]
        moved = 0
        for identity in self.duplicate_ids:
            duplicate = rows[identity]
            # Passes now count for the surviving pothole, so exposure is not split.
            moved += repo.move_passes(duplicate['pothole_id'], canonical['pothole_id'])
            repo.change_status(duplicate, 'REJECTED', actor_id, f'Duplicado del reporte {self.canonical_id}')
        return {'duplicates': len(self.duplicate_ids), 'passesMoved': moved}


class CommandExecutor:
    """Invoker: the single path every maintenance write follows."""

    def __init__(self, engine):
        self.engine = engine

    def run(self, command: MaintenanceCommand, session: dict) -> dict:
        with self.engine.begin() as conn:
            repo = MaintenanceRepository(conn)
            if command.lock_key is not None:
                repo.advisory_lock(command.lock_key)
            rows = repo.lock_reports(command.report_ids())
            command.rules().handle(ValidationContext(command, rows))
            details = command.apply(repo, rows, session['user_id'])
            AuditLog.record(conn, session['id'], command.action, command.entity_id, details)
        return details
