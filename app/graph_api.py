"""Authenticated, bounded query of the proximity graph between public reports."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from . import schema as s
from .auth import SessionGuard
from .report_graphs import ReportProximityGraph


class GraphController:
    """GET /api/data-structures/graphs/reports: BFS/DFS and Dijkstra over nearby potholes."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/data-structures/graphs')
        self.router.add_api_route('/reports', self.report_graph, methods=['GET'],
                                  dependencies=[Depends(SessionGuard.current)])

    def report_graph(self, request: Request, radius: int = Query(250, ge=50, le=2000),
                     limit: int = Query(80, ge=1, le=80), order: Literal['bfs', 'dfs'] = 'bfs',
                     start: UUID | None = None, end: UUID | None = None):
        reports, total, _ = request.app.state.repo.tree_reports(0, 100, limit)
        network = ReportProximityGraph(reports, radius)
        try:
            graph = network.snapshot(str(start) if start else None, str(end) if end else None, order)
        except ValueError:
            raise HTTPException(404, 'El reporte seleccionado ya no está disponible en esta muestra. Actualiza el grafo.') from None
        return {'generatedAt': s.Clock.now(), 'scope': {'totalReports': total, 'loaded': len(network.reports),
                'limit': limit, 'hasMore': total > len(reports), 'excluded': len(reports) - len(network.reports),
                'selection': 'highest-risk', 'radiusMeters': radius, 'edgeMeaning': 'geographic-proximity'},
                'graph': graph, 'reports': network.ordered_reports()}
