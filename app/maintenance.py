"""Maintenance domain for the Operator role: workflow, priority and day route.

Everything here is pure (no database) so it can be tested in isolation. The
API module ``operator_api`` loads reports from PostgreSQL and uses these classes.
"""
import math
from dataclasses import dataclass
from .priority_queue import IndexedMaxHeap
from .geo import GeoMath
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


class RoutePlanner:
    """Orders a day's stops to reduce the walking or driving distance.

    The exact problem is the travelling salesman path (NP-hard). We use the
    nearest neighbour heuristic, O(k^2), and then improve it with 2-opt, which
    reverses a segment whenever that shortens the path, O(k^2) per pass.
    Distances are straight-line (haversine), not road distances.
    """

    MAX_PASSES = 50

    def __init__(self, start: dict | None, stops: list[dict]):
        self.start = start
        self.stops = stops
        points = ([start] if start else []) + [stop['location'] for stop in stops]
        self.offset = 1 if start else 0
        # Distance matrix: a two-dimensional array, symmetric with zero diagonal.
        self.matrix = [[0.0] * len(points) for _ in points]
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                self.matrix[i][j] = self.matrix[j][i] = GeoMath.distance(points[i], points[j])
        self.improvements = 0

    def length(self, path: list[int]) -> float:
        return sum(self.matrix[a][b] for a, b in zip(path, path[1:]))

    def priority_path(self) -> list[int]:
        """Baseline: visit the stops in the received (priority) order."""
        return list(range(len(self.matrix)))

    def nearest_neighbour(self) -> list[int]:
        size = len(self.matrix)
        if size == 0:
            return []
        path = [0]
        unvisited = set(range(1, size))
        while unvisited:
            last = path[-1]
            following = min(unvisited, key=lambda node: (self.matrix[last][node], node))
            path.append(following)
            unvisited.remove(following)
        return path

    def two_opt(self, path: list[int]) -> list[int]:
        """Open path 2-opt; the first node is fixed when the route has a start point."""
        path = list(path)
        first = 1 if self.start else 0
        improved, passes = True, 0
        while improved and passes < self.MAX_PASSES:
            improved, passes = False, passes + 1
            for i in range(max(first, 1), len(path) - 1):
                for j in range(i + 1, len(path)):
                    before = self.matrix[path[i - 1]][path[i]]
                    after = self.matrix[path[i - 1]][path[j]]
                    if j + 1 < len(path):
                        before += self.matrix[path[j]][path[j + 1]]
                        after += self.matrix[path[i]][path[j + 1]]
                    if after + 1e-9 < before:
                        path[i:j + 1] = reversed(path[i:j + 1])
                        improved = True
                        self.improvements += 1
            if not self.start and len(path) > 2:
                # Without a fixed start, also try reversing a prefix (moves the first stop).
                for j in range(1, len(path) - 1):
                    before = self.matrix[path[j]][path[j + 1]]
                    after = self.matrix[path[0]][path[j + 1]]
                    if after + 1e-9 < before:
                        path[:j + 1] = reversed(path[:j + 1])
                        improved = True
                        self.improvements += 1
        return path

    def plan(self) -> dict:
        baseline = self.priority_path()
        path = self.two_opt(self.nearest_neighbour())
        if self.length(path) > self.length(baseline):
            path = baseline  # Never return something worse than the priority order.
        order = [node - self.offset for node in path if node >= self.offset]
        # Distance travelled to reach each stop; the first stop has none without a start point.
        legs = [round(self.matrix[path[position - 1]][node], 1) if position else None
                for position, node in enumerate(path) if node >= self.offset]
        planned, original = self.length(path), self.length(baseline)
        return {'order': order, 'legsMeters': legs, 'totalMeters': round(planned, 1),
                'priorityOrderMeters': round(original, 1),
                'savedPercent': round(100 * (original - planned) / original, 1) if original else 0.0,
                'improvements': self.improvements}
