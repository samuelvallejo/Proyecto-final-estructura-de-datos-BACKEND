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
