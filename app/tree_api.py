"""Tree snapshots built from public reports; a session is required."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from . import schema as s
from .auth import SessionGuard
from .report_trees import ReportPlaceTree, ReportRiskIndex

Traversal = Literal['inorder', 'descending', 'preorder', 'postorder', 'level']


class TreeController:
    """GET /api/data-structures/trees/reports: risk BST and place tree over the riskiest reports."""

    def __init__(self):
        self.router = APIRouter(prefix='/api/data-structures/trees')
        self.router.add_api_route('/reports', self.report_trees, methods=['GET'],
                                  dependencies=[Depends(SessionGuard.current)])

    def report_trees(self, request: Request, minScore: int = Query(0, ge=0, le=100),
                     maxScore: int = Query(100, ge=0, le=100), limit: int = Query(200, ge=1, le=200),
                     order: Traversal = 'inorder'):
        if minScore > maxScore:
            raise HTTPException(422, 'El riesgo mínimo no puede superar al máximo.')
        reports, total, matched = request.app.state.repo.tree_reports(minScore, maxScore, limit)
        index = ReportRiskIndex(reports)
        places = ReportPlaceTree(reports)
        loaded = len(index.by_id)
        return {'generatedAt': s.Clock.now(), 'scope': {'totalReports': total, 'totalMatched': matched,
                'loaded': loaded, 'limit': limit, 'hasMore': matched > loaded,
                'minScore': minScore, 'maxScore': maxScore, 'selection': 'highest-risk'},
                'binary': index.snapshot(order), 'geography': places.snapshot(), 'reports': index.ordered(order)}
