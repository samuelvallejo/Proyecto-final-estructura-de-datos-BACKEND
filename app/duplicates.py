"""Groups reports that very likely describe the same physical pothole.

1. A spatial hash grid finds every pair of potholes closer than ``radius``.
2. A disjoint-set forest joins each close pair; its sets are the clusters
   (single-linkage clustering: A~B and B~C put A, B and C together).
3. Each cluster suggests a canonical report (the first one registered) that
   keeps the history; the others are proposed as duplicates for human review.
"""
from dataclasses import dataclass
from .disjoint_set import DisjointSet
from .geo import GeoMath
from .spatial_index import SpatialHashGrid


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

    def __init__(self, reports: list[dict], radius: float):
        if not self.MIN_RADIUS <= radius <= self.MAX_RADIUS:
            raise ValueError('Radius out of range')
        self.radius = float(radius)
        # One vertex per physical pothole; its earliest report represents it.
        by_pothole: dict[str, dict] = {}
        for report in sorted(reports, key=lambda item: (item['timestamp'], item['id'])):
            by_pothole.setdefault(report.get('potholeId') or report['id'], report)
        self.reports = by_pothole
        self.grid = SpatialHashGrid[str](self.radius)
        self.skipped = [key for key, report in by_pothole.items()
                        if not self.grid.insert(key, report['location']['lat'], report['location']['lng'])]
        self.sets = DisjointSet[str](self.grid.points)
        self.pairs, self.checks = self.grid.close_pairs(self.radius)
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
        indexed = len(self.grid)
        clusters = self.clusters()
        return {'potholes': len(self.reports), 'indexed': indexed, 'skipped': len(self.skipped),
                'closePairs': len(self.pairs), 'candidateChecks': self.checks,
                'bruteForceChecks': indexed * (indexed - 1) // 2, 'clusters': len(clusters),
                'duplicates': sum(len(cluster.duplicates) for cluster in clusters),
                'estimatedPhysicalPotholes': self.sets.sets, 'radiusMeters': self.radius}
