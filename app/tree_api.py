"""Instantáneas de árboles construidas con reportes públicos y sesión obligatoria."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from .auth import current_session
from .report_trees import ReportRiskIndex, ReportPlaceTree
from . import schema as s

router = APIRouter(prefix='/api/data-structures/trees')
Traversal = Literal['inorder', 'descending', 'preorder', 'postorder', 'level']


@router.get('/reports', dependencies=[Depends(current_session)])
def report_trees(request: Request, minScore: int = Query(0, ge=0, le=100),
                 maxScore: int = Query(100, ge=0, le=100), limit: int = Query(200, ge=1, le=200),
                 order: Traversal = 'inorder'):
    if minScore > maxScore:
        raise HTTPException(422, 'El riesgo mínimo no puede superar al máximo.')
    reports, total, matched = request.app.state.repo.tree_reports(minScore, maxScore, limit)
    index = ReportRiskIndex(reports)
    places = ReportPlaceTree(reports)
    return {'generatedAt': s.now(), 'scope': {'totalReports': total, 'totalMatched': matched,
        'loaded': len(index.by_id), 'limit': limit, 'hasMore': matched > len(index.by_id),
        'minScore': minScore, 'maxScore': maxScore, 'selection': 'highest-risk'},
        'binary': index.snapshot(order), 'geography': places.snapshot(), 'reports': index.ordered(order)}
