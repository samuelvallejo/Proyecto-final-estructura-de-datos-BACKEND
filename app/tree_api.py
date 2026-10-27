"""Instantáneas de árboles construidas con reportes públicos y sesión obligatoria."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from .auth import current_session
from .report_trees import ReportRiskIndex, ReportPlaceTree
from . import schema as s

router = APIRouter(prefix='/api/data-structures/trees')
Traversal = Literal['inorder', 'descending', 'preorder', 'postorder', 'level']
