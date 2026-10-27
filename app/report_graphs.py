"""Red temporal de cercanía entre reportes activos; no representa la red vial."""
from math import isfinite
from .graphs import WeightedGraph
from .repository import distance


class ReportProximityGraph:
    def __init__(self, reports: list[dict], radius: int):
        if not 50 <= radius <= 2000:
            raise ValueError('Radio fuera del rango permitido')
        self.graph = WeightedGraph()
        self.reports = {}
        for report in reports:
            position = report['location']
            if all(isinstance(position[k], (int, float)) and not isinstance(position[k], bool)
                   and isfinite(position[k]) and -bound <= position[k] <= bound
                   for k, bound in [('lat', 90), ('lng', 180)]):
                self.reports[report['id']] = report
        self.reports = dict(sorted(self.reports.items()))
        for identity in self.reports:
            self.graph.add_vertex(identity)
        ids = list(self.reports)
        for i, source in enumerate(ids):
            for target in ids[i + 1:]:
                meters = distance(self.reports[source]['location'], self.reports[target]['location'])
                if meters <= radius:
                    self.graph.add_edge(source, target, meters)

    def snapshot(self, start=None, end=None, order='bfs'):
        if start is not None and start not in self.reports or end is not None and end not in self.reports:
            raise ValueError('El reporte no está en esta muestra')
        start = start if start is not None else next(iter(self.reports), None)
        groups = self.graph.components()
        components = {identity: index + 1 for index, group in enumerate(groups) for identity in group}
        edges = self.graph.edges()
        return {'directed': False, 'weighted': True, 'representation': 'adjacency-list',
                'nodes': [{'id': identity, 'degree': len(neighbors), 'component': components[identity]}
                          for identity, neighbors in self.graph.adjacency.items()],
                'edges': edges, 'components': groups,
                'metrics': {'vertices': len(self.reports), 'edges': len(edges), 'components': len(groups),
                            'isolated': sum(not n for n in self.graph.adjacency.values()),
                            'maxDegree': max((len(n) for n in self.graph.adjacency.values()), default=0)},
                'traversal': {'order': order, 'startId': start,
                              'reportIds': self.graph.traverse(start, order) if start else []},
                'path': self.graph.shortest_path(start, end) if start and end else None}
