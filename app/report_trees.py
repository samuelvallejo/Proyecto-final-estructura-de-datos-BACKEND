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


def place_key(value):
    text = ' '.join((value or '').split()).casefold()
    return ''.join(char for char in unicodedata.normalize('NFKD', text) if not unicodedata.combining(char))


def place_id(path):
    # Longitudes evitan colisiones por separadores dentro de nombres de calles.
    encoded = ''.join(f'{len(part)}:{part}' for part in path)
    return 'place-' + sha256(encoded.encode('utf-8')).hexdigest()[:24]


class ReportPlaceTree:
    def __init__(self, reports=()):
        self.root = PlaceNode('places-root', 'Reportes viales', 'root')
        self.nodes = {self.root.id: self.root}
        self.parents = {}
        unique = {report['id']: report for report in reports}
        for report in sorted(unique.values(), key=lambda item: item['id']):
            parent = self.root
            path = []
            score = report_key(report)[0]
            parent.report_count += 1
            parent.highest_score = max(parent.highest_score, score)
            for kind, fallback in [('city', 'Ciudad sin identificar'), ('neighborhood', 'Barrio sin identificar'), ('street', 'Vía sin identificar')]:
                raw = report['zone'].get(kind)
                label = ' '.join(raw.split()) if raw and raw.strip() else fallback
                path.append(kind + ':' + (place_key(raw) if raw and raw.strip() else '~unknown'))
                identity = place_id(path)
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
            leaf = PlaceNode(identity, f"Bache · Riesgo {score}/100", 'report', report['id'], report_count=1, highest_score=score)
            self.nodes[identity] = leaf
            self.parents[identity] = parent.id
            parent.children.append(leaf)
        for node in self.nodes.values():
            node.children.sort(key=lambda child: (place_key(child.label), child.id))

    def walk(self):
        pending = [(self.root, 1)]
        while pending:
            node, level = pending.pop()
            yield node, level
            pending.extend((child, level + 1) for child in reversed(node.children))

    def metrics(self):
        levels = max((level for _, level in self.walk()), default=0)
        leaves = sum(not node.children for node in self.nodes.values())
        return {'weight': len(self.nodes), 'height': levels - 1, 'levels': levels,
                'leaves': leaves, 'branches': sum(bool(node.children) for node in self.nodes.values()) - bool(self.root.children),
                'maxDegree': max((len(node.children) for node in self.nodes.values()), default=0),
                'reports': self.root.report_count}

    def path_to(self, node_id):
        if node_id not in self.nodes:
            return []
        result = []
        while node_id is not None:
            result.append(self.nodes[node_id])
            node_id = self.parents.get(node_id)
        return list(reversed(result))
