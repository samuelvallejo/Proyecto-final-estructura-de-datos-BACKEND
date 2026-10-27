"""Índices en memoria de reportes públicos; PostgreSQL sigue siendo persistencia."""
import math
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256
from .trees import BinarySearchTree


def report_key(report):
    score, timestamp, identity = report['hazardScore'], report['timestamp'], report['id']
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError('Puntuación inválida')
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError('Fecha inválida')
    if not isinstance(identity, str) or not identity:
        raise ValueError('Identificador inválido')
    return score, timestamp, identity


class ReportRiskIndex:
    def __init__(self, reports=()):
        self.by_id = {report['id']: report for report in reports}
        self.tree = BinarySearchTree.from_items((report_key(report), report) for report in self.by_id.values())

    def upsert(self, report):
        key = report_key(report)
        previous = self.by_id.get(report['id'])
        if previous is not None:
            self.tree.remove(report_key(previous))
        self.by_id[report['id']] = report
        self.tree.insert(key, report)

    def remove(self, report_id):
        previous = self.by_id.pop(report_id, None)
        return self.tree.remove(report_key(previous)) if previous is not None else False

    def ordered(self, order='descending'):
        return [node.value for node in self.tree.traverse(order)]

    def in_range(self, minimum=0, maximum=100):
        if not 0 <= minimum <= maximum <= 100:
            raise ValueError('Rango de riesgo inválido')
        return [node.value for node in self.tree.between((minimum, -math.inf, ''), (maximum, math.inf, chr(0x10ffff)))]

    def search_path(self, report_id):
        report = self.by_id.get(report_id)
        return [node.value['id'] for node in self.tree.trace(report_key(report))] if report is not None else []

    def snapshot(self, order='inorder'):
        nodes = []
        for node, level, parent in self.tree.level_order():
            nodes.append({'id': node.value['id'], 'score': node.key[0],
                'leftId': node.left.value['id'] if node.left is not None else None,
                'rightId': node.right.value['id'] if node.right is not None else None,
                'parentId': parent.value['id'] if parent is not None else None,
                'level': level, 'degree': int(node.left is not None) + int(node.right is not None),
                'isLeaf': node.left is None and node.right is None})
        return {'rootId': self.tree.root.value['id'] if self.tree.root is not None else None,
                'nodes': nodes, 'metrics': self.tree.metrics(),
                'traversal': {'order': order, 'reportIds': [node.value['id'] for node in self.tree.traverse(order)]}}


@dataclass
class PlaceNode:
    id: str
    label: str
    kind: str
    report_id: str | None = None
    children: list['PlaceNode'] = field(default_factory=list)
    report_count: int = 0
    highest_score: int = 0
