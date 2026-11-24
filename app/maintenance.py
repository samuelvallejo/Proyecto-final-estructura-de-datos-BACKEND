"""Maintenance domain for the Operator role: workflow, priority and day route.

Everything here is pure (no database) so it can be tested in isolation. The
API module ``operator_api`` loads reports from PostgreSQL and uses these classes.
"""
import math
from dataclasses import dataclass
from .priority_queue import IndexedMaxHeap
from .route_planning import RoutePlanner  # noqa: F401  (re-exported for callers of this module)
from .structures import Queue

DAY_MS = 86_400_000


class StatusWorkflow:
    """Directed graph of the allowed pothole status changes for field staff.

    Vertices are statuses and edges are allowed transitions. REPAIRED and
    REJECTED have no outgoing edges: only an administrator can reopen them
    through the administration endpoint.
    """

    TRANSITIONS: dict[str, tuple[str, ...]] = {
        'UNVERIFIED': ('CONFIRMED', 'REJECTED'),
        'CONFIRMED': ('IN_PROGRESS', 'REJECTED'),
        'IN_PROGRESS': ('REPAIRED', 'CONFIRMED'),
        'REPAIRED': (),
        'REJECTED': (),
    }
    OPEN_STATUSES = ('UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS')

    def __init__(self, transitions: dict[str, tuple[str, ...]] | None = None):
        self.transitions = transitions or self.TRANSITIONS
        unknown = {target for targets in self.transitions.values() for target in targets} - set(self.transitions)
        if unknown:
            raise ValueError('Every transition target must be a known status')

    def allowed(self, status: str) -> list[str]:
        return list(self.transitions.get(status, ()))

    def can_move(self, current: str, target: str) -> bool:
        return target in self.transitions.get(current, ())

    def is_terminal(self, status: str) -> bool:
        return status in self.transitions and not self.transitions[status]

    def shortest_path(self, current: str, target: str) -> list[str]:
        """Fewest transitions from ``current`` to ``target`` (BFS); empty if unreachable."""
        if current not in self.transitions or target not in self.transitions:
            return []
        parents: dict[str, str | None] = {current: None}
        pending = Queue[str]()
        pending.enqueue(current)
        while pending.size:
            status = pending.dequeue()
            if status == target:
                path = [status]
                while parents[path[-1]] is not None:
                    path.append(parents[path[-1]])
                return path[::-1]
            for neighbor in self.transitions[status]:
                if neighbor not in parents:
                    parents[neighbor] = status
                    pending.enqueue(neighbor)
        return []


@dataclass(frozen=True)
class PriorityBreakdown:
    """Explainable maintenance score; components add up to ``score`` (0 to 100)."""
    score: float
    hazard: float
    exposure: float
    traffic: float
    waiting: float
    status: float

    def as_dict(self) -> dict:
        return {'score': self.score, 'components': {'hazard': self.hazard, 'exposure': self.exposure,
                'traffic': self.traffic, 'waiting': self.waiting, 'status': self.status}}


class MaintenancePriority:
    """Weighted score that decides which pothole should be attended first.

    hazard   up to 55 points: visual or community risk score (0 to 100).
    exposure up to 20 points: distinct people that passed the pothole (log scale).
    traffic  up to 10 points: total recorded passes (log scale).
    waiting  up to 10 points: aging, half a point per day without repair, so old
             reports cannot starve behind newer high risk ones.
    status   up to 5 points: confirmed or in progress work is already validated.
    """

    HAZARD_WEIGHT = 55
    EXPOSURE_WEIGHT = 20
    TRAFFIC_WEIGHT = 10
    WAITING_POINTS_PER_DAY = 0.5
    WAITING_CAP = 10
    STATUS_BONUS = {'UNVERIFIED': 0.0, 'CONFIRMED': 5.0, 'IN_PROGRESS': 5.0}
    PEOPLE_SATURATION = 20
    PASSES_SATURATION = 50

    @staticmethod
    def _log_ratio(value: float, saturation: int) -> float:
        return min(1.0, math.log1p(max(0.0, value)) / math.log1p(saturation))

    def evaluate(self, report: dict, now: int) -> PriorityBreakdown:
        hazard = self.HAZARD_WEIGHT * min(100.0, max(0.0, float(report['hazardScore']))) / 100
        exposure = self.EXPOSURE_WEIGHT * self._log_ratio(report.get('peopleCount') or 0, self.PEOPLE_SATURATION)
        traffic = self.TRAFFIC_WEIGHT * self._log_ratio(report.get('passCount') or 0, self.PASSES_SATURATION)
        days = max(0, now - report['timestamp']) / DAY_MS
        waiting = min(self.WAITING_CAP, days * self.WAITING_POINTS_PER_DAY)
        status = self.STATUS_BONUS.get(report.get('status'), 0.0)
        parts = [round(value, 2) for value in (hazard, exposure, traffic, waiting, status)]
        return PriorityBreakdown(round(sum(parts), 2), *parts)


class MaintenanceQueue:
    """Ranks open reports with an indexed max-heap built in O(n)."""

    def __init__(self, reports: list[dict], now: int, policy: MaintenancePriority | None = None):
        self.policy = policy or MaintenancePriority()
        self.reports = {report['id']: report for report in reports}
        self.breakdowns = {identity: self.policy.evaluate(report, now) for identity, report in self.reports.items()}
        # Ties: older report first, then the heap breaks remaining ties by id.
        self.heap = IndexedMaxHeap((identity, (breakdown.score, -self.reports[identity]['timestamp']))
                                   for identity, breakdown in self.breakdowns.items())

    def __len__(self) -> int:
        return len(self.heap)

    def top(self, limit: int) -> list[tuple[dict, PriorityBreakdown]]:
        return [(self.reports[identity], self.breakdowns[identity]) for identity, _ in self.heap.top(limit)]
