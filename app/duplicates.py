"""Groups reports that very likely describe the same physical pothole.

1. A spatial hash grid finds every pair of potholes closer than ``radius``.
2. A disjoint-set forest joins each close pair; its sets are the clusters
   (single-linkage clustering: A~B and B~C put A, B and C together).
3. Each cluster suggests a canonical report (the first one registered) that
   keeps the history; the others are proposed as duplicates for human review.

Design pattern: Strategy. How close pairs are found is a ``NeighbourFinder``:
the spatial grid in production, or brute force as the reference that shows
how many comparisons the grid avoids.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from .disjoint_set import DisjointSet
from .geo import GeoMath
from .spatial_index import SpatialHashGrid


Pair = tuple[str, str, float]


class NeighbourFinder(ABC):
    """Strategy: index points and return every pair closer than the radius."""

    name = ''

    def __init__(self, radius: float):
        self.radius = float(radius)

    @abstractmethod
    def insert(self, key: str, lat: float, lng: float) -> bool:
        """False when the point cannot be indexed (invalid or near a pole)."""

    @abstractmethod
    def close_pairs(self) -> tuple[list[Pair], int]:
        """Close pairs and the number of exact distance checks performed."""

    @property
    @abstractmethod
    def keys(self) -> list[str]: ...


class GridNeighbourFinder(NeighbourFinder):
    """Spatial hash grid: O(n + m) expected checks."""

    name = 'grid'

    def __init__(self, radius: float):
        super().__init__(radius)
        self.grid = SpatialHashGrid[str](self.radius)

    def insert(self, key: str, lat: float, lng: float) -> bool:
        return self.grid.insert(key, lat, lng)

    def close_pairs(self) -> tuple[list[Pair], int]:
        return self.grid.close_pairs(self.radius)

    @property
    def keys(self) -> list[str]:
        return list(self.grid.points)


class BruteForceNeighbourFinder(NeighbourFinder):
    """Every pair is compared: n(n-1)/2 checks. Reference for correctness and cost."""

    name = 'brute-force'

    def __init__(self, radius: float):
        super().__init__(radius)
        self.points: dict[str, dict] = {}

    def insert(self, key: str, lat: float, lng: float) -> bool:
        if not SpatialHashGrid.valid(lat, lng):  # Same accepted points as the grid.
            return False
        self.points[key] = {'lat': lat, 'lng': lng}
        return True

    def close_pairs(self) -> tuple[list[Pair], int]:
        keys, pairs, checks = list(self.points), [], 0
        for index, first in enumerate(keys):
            for second in keys[index + 1:]:
                checks += 1
                meters = GeoMath.distance(self.points[first], self.points[second])
                if meters <= self.radius:
                    pairs.append((first, second, meters))
        return pairs, checks

    @property
    def keys(self) -> list[str]:
        return list(self.points)


FINDERS: dict[str, type[NeighbourFinder]] = {finder.name: finder for finder in (GridNeighbourFinder, BruteForceNeighbourFinder)}


@dataclass(frozen=True)
class DuplicateCluster:
    canonical: dict
    duplicates: list[dict]
    max_span_meters: float

    def as_dict(self) -> dict:
        return {'canonical': self.canonical, 'duplicates': self.duplicates,
                'size': 1 + len(self.duplicates), 'maxSpanMeters': round(self.max_span_meters, 1)}


class DuplicateDetector:
    MIN_RADIUS = 1
    MAX_RADIUS = 50

    def __init__(self, reports: list[dict], radius: float, method: str = GridNeighbourFinder.name):
        if not self.MIN_RADIUS <= radius <= self.MAX_RADIUS:
            raise ValueError('Radius out of range')
        self.radius = float(radius)
        # One vertex per physical pothole; its earliest report represents it.
        by_pothole: dict[str, dict] = {}
        for report in sorted(reports, key=lambda item: (item['timestamp'], item['id'])):
            by_pothole.setdefault(report.get('potholeId') or report['id'], report)
        self.reports = by_pothole
        if method not in FINDERS:
            raise ValueError('Unknown neighbour search method')
        self.finder = FINDERS[method](self.radius)
        self.skipped = [key for key, report in by_pothole.items()
                        if not self.finder.insert(key, report['location']['lat'], report['location']['lng'])]
        self.sets = DisjointSet[str](self.finder.keys)
        self.pairs, self.checks = self.finder.close_pairs()
        for first, second, _ in self.pairs:
            self.sets.union(first, second)

    def clusters(self) -> list[DuplicateCluster]:
        result = []
        for group in self.sets.groups():
            if len(group) < 2:
                continue
            members = sorted((self.reports[key] for key in group), key=lambda item: (item['timestamp'], item['id']))
            span = max(GeoMath.distance(a['location'], b['location']) for index, a in enumerate(members) for b in members[index + 1:])
            result.append(DuplicateCluster(members[0], members[1:], span))
        # Largest and highest-risk clusters first, so the review starts with the worst noise.
        return sorted(result, key=lambda cluster: (-len(cluster.duplicates), -max(item['hazardScore'] for item in
                      [cluster.canonical, *cluster.duplicates]), cluster.canonical['id']))

    def stats(self) -> dict:
        indexed = len(self.finder.keys)
        clusters = self.clusters()
        return {'potholes': len(self.reports), 'indexed': indexed, 'skipped': len(self.skipped),
                'closePairs': len(self.pairs), 'candidateChecks': self.checks,
                'bruteForceChecks': indexed * (indexed - 1) // 2, 'clusters': len(clusters),
                'duplicates': sum(len(cluster.duplicates) for cluster in clusters),
                'estimatedPhysicalPotholes': self.sets.sets, 'radiusMeters': self.radius,
                'method': self.finder.name}
