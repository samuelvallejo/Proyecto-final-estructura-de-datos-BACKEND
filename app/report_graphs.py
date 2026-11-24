"""Temporary proximity network between active reports; it does not model the road network."""
from math import isfinite

from .geo import GeoMath
from .graphs import WeightedGraph
from .structures import DynamicArray, HashMap, Sorter


class ReportProximityGraph:
    """Connects reports that are at most ``radius`` meters apart (edge weight = distance)."""
    MIN_RADIUS, MAX_RADIUS = 50, 2000

    def __init__(self, reports, radius: int):
        if not self.MIN_RADIUS <= radius <= self.MAX_RADIUS:
            raise ValueError('Radius outside the allowed range')
        self.graph = WeightedGraph()
        self.reports = HashMap[str, dict]()
        for report in reports:
            if self._valid_position(report['location']):
                self.reports[report['id']] = report
        ids = DynamicArray(Sorter.merge_sort(self.reports.keys()))
        for identity in ids:
            self.graph.add_vertex(identity)
        for i in range(ids.size):
            for j in range(i + 1, ids.size):
                source, target = ids[i], ids[j]
                meters = GeoMath.distance(self.reports[source]['location'], self.reports[target]['location'])
                if meters <= radius:
                    self.graph.add_edge(source, target, meters)

    @staticmethod
    def _valid_position(position: dict) -> bool:
        for key, bound in (('lat', 90), ('lng', 180)):
            value = position[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not -bound <= value <= bound:
                return False
        return True

    def ordered_reports(self) -> list[dict]:
        """Reports in ascending id order, as sent to the client."""
        return [self.reports[identity] for identity in self.graph.vertices()]

    def snapshot(self, start=None, end=None, order='bfs') -> dict:
        if start is not None and start not in self.reports or end is not None and end not in self.reports:
            raise ValueError('The report is not part of this sample')
        vertices = self.graph.vertices()
        start = start if start is not None else (vertices.head.value if vertices.head else None)
        groups = self.graph.components()
        component_of = HashMap[str, int]()
        for index, group in enumerate(groups):
            for identity in group:
                component_of[identity] = index + 1
        edges = self.graph.edges()
        degrees = [self.graph.degree(identity) for identity in vertices]
        return {'directed': False, 'weighted': True, 'representation': 'adjacency-list',
                'nodes': [{'id': identity, 'degree': self.graph.degree(identity), 'component': component_of[identity]}
                          for identity in vertices],
                'edges': edges, 'components': groups,
                'metrics': {'vertices': len(self.reports), 'edges': len(edges), 'components': len(groups),
                            'isolated': sum(1 for degree in degrees if degree == 0),
                            'maxDegree': max(degrees, default=0)},
                'traversal': {'order': order, 'startId': start,
                              'reportIds': self.graph.traverse(start, order) if start else []},
                'path': self.graph.shortest_path(start, end) if start and end else None}
