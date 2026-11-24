"""Day route planning with interchangeable algorithms.

Design patterns
* Strategy: a route is built by a ``RouteConstruction`` and then refined by a
  ``RouteImprovement``. Each step is a class with one method, so algorithms are
  swapped without touching ``RoutePlanner``.
* Factory: ``RoutePlannerFactory`` turns the public algorithm name of the API
  (``two-opt``, ``nearest-neighbour``, ``priority``) into a configured planner.

The exact problem is the travelling salesman path (NP-hard); these are
heuristics over straight-line (haversine) distances, not road routes.
"""
from abc import ABC, abstractmethod
from .geo import GeoMath

Matrix = list[list[float]]


def path_length(matrix: Matrix, path: list[int]) -> float:
    return sum(matrix[a][b] for a, b in zip(path, path[1:]))


class RouteConstruction(ABC):
    """Strategy: produce a first visiting order (node 0 is the start when it is fixed)."""

    @abstractmethod
    def build(self, matrix: Matrix) -> list[int]: ...


class PriorityOrderConstruction(RouteConstruction):
    """Visit the stops in the received order (highest priority first). O(k)."""

    def build(self, matrix: Matrix) -> list[int]:
        return list(range(len(matrix)))


class NearestNeighbourConstruction(RouteConstruction):
    """Always go to the closest unvisited stop. O(k^2)."""

    def build(self, matrix: Matrix) -> list[int]:
        if not matrix:
            return []
        path, unvisited = [0], set(range(1, len(matrix)))
        while unvisited:
            last = path[-1]
            following = min(unvisited, key=lambda node: (matrix[last][node], node))
            path.append(following)
            unvisited.remove(following)
        return path


class RouteImprovement(ABC):
    """Strategy: refine an order; returns the new order and how many changes it made."""

    @abstractmethod
    def improve(self, matrix: Matrix, path: list[int], fixed_start: bool) -> tuple[list[int], int]: ...


class NoImprovement(RouteImprovement):
    def improve(self, matrix: Matrix, path: list[int], fixed_start: bool) -> tuple[list[int], int]:
        return list(path), 0


class TwoOptImprovement(RouteImprovement):
    """Reverse a segment whenever that shortens the open path. O(k^2) per pass."""

    MAX_PASSES = 50

    def improve(self, matrix: Matrix, path: list[int], fixed_start: bool) -> tuple[list[int], int]:
        path, changes = list(path), 0
        improved, passes = True, 0
        while improved and passes < self.MAX_PASSES:
            improved, passes = False, passes + 1
            for i in range(1, len(path) - 1):
                for j in range(i + 1, len(path)):
                    before = matrix[path[i - 1]][path[i]]
                    after = matrix[path[i - 1]][path[j]]
                    if j + 1 < len(path):
                        before += matrix[path[j]][path[j + 1]]
                        after += matrix[path[i]][path[j + 1]]
                    if after + 1e-9 < before:
                        path[i:j + 1] = reversed(path[i:j + 1])
                        improved, changes = True, changes + 1
            if not fixed_start and len(path) > 2:
                # Without a fixed start, reversing a prefix may also move the first stop.
                for j in range(1, len(path) - 1):
                    if matrix[path[0]][path[j + 1]] + 1e-9 < matrix[path[j]][path[j + 1]]:
                        path[:j + 1] = reversed(path[:j + 1])
                        improved, changes = True, changes + 1
        return path, changes


class RoutePlanner:
    """Orders a day's stops with the configured construction and improvement strategies."""

    def __init__(self, start: dict | None, stops: list[dict], construction: RouteConstruction | None = None,
                 improvement: RouteImprovement | None = None, name: str = 'two-opt'):
        self.start = start
        self.stops = stops
        self.construction = construction or NearestNeighbourConstruction()
        self.improvement = improvement or TwoOptImprovement()
        self.name = name
        points = ([start] if start else []) + [stop['location'] for stop in stops]
        self.offset = 1 if start else 0
        # Distance matrix: a two-dimensional array, symmetric with zero diagonal.
        self.matrix: Matrix = [[0.0] * len(points) for _ in points]
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                self.matrix[i][j] = self.matrix[j][i] = GeoMath.distance(points[i], points[j])
        self.improvements = 0

    def length(self, path: list[int]) -> float:
        return path_length(self.matrix, path)

    def plan(self) -> dict:
        baseline = PriorityOrderConstruction().build(self.matrix)
        path, self.improvements = self.improvement.improve(self.matrix, self.construction.build(self.matrix), bool(self.start))
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
                'improvements': self.improvements, 'algorithm': self.name}


class RoutePlannerFactory:
    """Factory: public algorithm names mapped to strategy combinations."""

    ALGORITHMS: dict[str, tuple[type[RouteConstruction], type[RouteImprovement]]] = {
        'two-opt': (NearestNeighbourConstruction, TwoOptImprovement),
        'nearest-neighbour': (NearestNeighbourConstruction, NoImprovement),
        'priority': (PriorityOrderConstruction, NoImprovement),
    }
    DEFAULT = 'two-opt'

    @classmethod
    def names(cls) -> list[str]:
        return list(cls.ALGORITHMS)

    @classmethod
    def create(cls, algorithm: str, start: dict | None, stops: list[dict]) -> RoutePlanner:
        if algorithm not in cls.ALGORITHMS:
            raise ValueError('Unknown route algorithm')
        construction, improvement = cls.ALGORITHMS[algorithm]
        return RoutePlanner(start, stops, construction(), improvement(), algorithm)
