"""In-memory indexes over public reports; PostgreSQL remains the source of truth."""
from __future__ import annotations

import math
import unicodedata
from hashlib import sha256

from .structures import HashMap, SinglyLinkedList, Sorter, Stack
from .trees import BinarySearchTree


class ReportRiskIndex:
    """Binary search tree of reports keyed by (risk score, timestamp, id)."""

    def __init__(self, reports=()):
        self.by_id = HashMap[str, dict]()
        for report in reports:
            self.by_id[report['id']] = report
        self.tree = BinarySearchTree.from_items((self.key_of(report), report) for report in self.by_id.values())

    @staticmethod
    def key_of(report: dict) -> tuple:
        """Validated BST key; the timestamp and id break ties so every key is unique."""
        score, timestamp, identity = report['hazardScore'], report['timestamp'], report['id']
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError('Invalid score')
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError('Invalid timestamp')
        if not isinstance(identity, str) or not identity:
            raise ValueError('Invalid id')
        return score, timestamp, identity

    def upsert(self, report: dict) -> None:
        key = self.key_of(report)
        previous = self.by_id.get(report['id'])
        if previous is not None:
            self.tree.remove(self.key_of(previous))
        self.by_id[report['id']] = report
        self.tree.insert(key, report)

    def remove(self, report_id: str) -> bool:
        previous = self.by_id.remove(report_id)
        return self.tree.remove(self.key_of(previous)) if previous is not None else False

    def ordered(self, order: str = 'descending') -> list[dict]:
        return [node.value for node in self.tree.traverse(order)]

    def in_range(self, minimum: int = 0, maximum: int = 100) -> list[dict]:
        if not 0 <= minimum <= maximum <= 100:
            raise ValueError('Invalid risk range')
        lower, upper = (minimum, -math.inf, ''), (maximum, math.inf, chr(0x10ffff))
        return [node.value for node in self.tree.between(lower, upper)]

    def search_path(self, report_id: str) -> list[str]:
        report = self.by_id.get(report_id)
        return [node.value['id'] for node in self.tree.trace(self.key_of(report))] if report is not None else []

    def snapshot(self, order: str = 'inorder') -> dict:
        nodes = SinglyLinkedList[dict]()
        for node, level, parent in self.tree.level_order():
            nodes.append({'id': node.value['id'], 'score': node.key[0],
                          'leftId': node.left.value['id'] if node.left is not None else None,
                          'rightId': node.right.value['id'] if node.right is not None else None,
                          'parentId': parent.value['id'] if parent is not None else None,
                          'level': level, 'degree': int(node.left is not None) + int(node.right is not None),
                          'isLeaf': node.left is None and node.right is None})
        return {'rootId': self.tree.root.value['id'] if self.tree.root is not None else None,
                'nodes': list(nodes), 'metrics': self.tree.metrics(),
                'traversal': {'order': order, 'reportIds': [node.value['id'] for node in self.tree.traverse(order)]}}


class PlaceNode:
    """General-tree node: root → city → neighborhood → street → report."""

    def __init__(self, identity: str, label: str, kind: str, report_id: str | None = None,
                 report_count: int = 0, highest_score: int = 0):
        self.id = identity
        self.label = label
        self.kind = kind
        self.report_id = report_id
        self.children = SinglyLinkedList[PlaceNode]()
        self.report_count = report_count
        self.highest_score = highest_score


class PlaceKeys:
    """Normalization of place names and collision-free ids for the place tree."""

    @staticmethod
    def normalize(value: str | None) -> str:
        """Lowercase, collapse spaces and strip accents: ' BOGOTÁ  Norte ' → 'bogota norte'."""
        text = ' '.join((value or '').split()).casefold()
        return ''.join(char for char in unicodedata.normalize('NFKD', text) if not unicodedata.combining(char))

    @staticmethod
    def identity(path) -> str:
        # Length prefixes avoid collisions when street names contain the separator.
        encoded = ''.join(f'{len(part)}:{part}' for part in path)
        return 'place-' + sha256(encoded.encode('utf-8')).hexdigest()[:24]


class ReportPlaceTree:
    LEVELS = (('city', 'Ciudad sin identificar'), ('neighborhood', 'Barrio sin identificar'), ('street', 'Vía sin identificar'))

    def __init__(self, reports=()):
        self.root = PlaceNode('places-root', 'Reportes viales', 'root')
        self.nodes = HashMap[str, PlaceNode]([(self.root.id, self.root)])
        self.parents = HashMap[str, str]()
        unique = HashMap[str, dict]()
        for report in reports:
            unique[report['id']] = report
        for report in Sorter.merge_sort(unique.values(), key=lambda item: item['id']):
            self._insert(report)
        for node in self.nodes.values():
            node.children = Sorter.merge_sort(node.children, key=lambda child: (PlaceKeys.normalize(child.label), child.id))

    def _insert(self, report: dict) -> None:
        parent, path = self.root, SinglyLinkedList[str]()
        score = ReportRiskIndex.key_of(report)[0]
        parent.report_count += 1
        parent.highest_score = max(parent.highest_score, score)
        for kind, fallback in self.LEVELS:
            raw = report['zone'].get(kind)
            known = bool(raw and raw.strip())
            label = ' '.join(raw.split()) if known else fallback
            path.append(kind + ':' + (PlaceKeys.normalize(raw) if known else '~unknown'))
            identity = PlaceKeys.identity(path)
            child = self.nodes.get(identity)
            if child is None:
                child = PlaceNode(identity, label, kind)
                self.nodes[identity] = child
                self.parents[identity] = parent.id
                parent.children.append(child)
            child.report_count += 1
            child.highest_score = max(child.highest_score, score)
            parent = child
        identity = 'report-' + report['id']
        leaf = PlaceNode(identity, f'Bache · Riesgo {score}/100', 'report', report['id'], report_count=1, highest_score=score)
        self.nodes[identity] = leaf
        self.parents[identity] = parent.id
        parent.children.append(leaf)

    def walk(self):
        """Depth-first pre-order walk with a hand-written stack; yields ``(node, level)``."""
        pending = Stack[tuple]()
        pending.push((self.root, 1))
        while not pending.is_empty():
            node, level = pending.pop()
            yield node, level
            reversed_children = Stack[PlaceNode]()
            for child in node.children:
                reversed_children.push(child)
            for child in reversed_children:  # Push last child first so the first child is visited first.
                pending.push((child, level + 1))

    def metrics(self) -> dict:
        levels = max((level for _, level in self.walk()), default=0)
        leaves = sum(1 for node in self.nodes.values() if not node.children)
        return {'weight': len(self.nodes), 'height': levels - 1, 'levels': levels, 'leaves': leaves,
                'branches': sum(1 for node in self.nodes.values() if node.children) - bool(self.root.children),
                'maxDegree': max((len(node.children) for node in self.nodes.values()), default=0),
                'reports': self.root.report_count}

    def path_to(self, node_id: str) -> list[PlaceNode]:
        if node_id not in self.nodes:
            return []
        path = Stack[PlaceNode]()
        while node_id is not None:
            path.push(self.nodes[node_id])
            node_id = self.parents.get(node_id)
        return list(path)

    def snapshot(self) -> dict:
        return {'rootId': self.root.id, 'metrics': self.metrics(), 'nodes': [
            {'id': node.id, 'label': node.label, 'kind': node.kind, 'level': level,
             'parentId': self.parents.get(node.id), 'childIds': [child.id for child in node.children],
             'reportId': node.report_id, 'reportCount': node.report_count, 'highestScore': node.highest_score}
            for node, level in self.walk()]}
