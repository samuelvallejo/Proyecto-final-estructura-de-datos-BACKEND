"""Full-text search over reports: inverted index plus prefix trie.

* ``Tokenizer`` lowercases, removes accents and Spanish stop words.
* ``InvertedIndex`` maps each token to the set of report ids that contain it
  (a hash table of sets). A query intersects the sets, smallest first.
* ``PrefixTrie`` stores every indexed word and every place name. It expands the
  last word the user is still typing ("panam" -> "panamericana") and suggests
  place names by prefix.

* ``BitmapIndex`` filters by risk level, damage type and status with bitwise
  AND/OR and counts each facet with popcount.
* ``AvlTree`` keyed by (timestamp, id) answers date ranges in O(log n + k).

Building costs O(total characters). A query costs O(query length + size of the
smallest posting set) for exact words, plus the trie expansion of the last word.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from .avl_tree import AvlTree
from .bitmap_index import BitmapIndex
from .priority_queue import IndexedMaxHeap
from .structures import Stack

STOP_WORDS = frozenset('a al con de del el en la las lo los para por sin su un una y o e'.split())
FIELD_WEIGHTS = {'place': 3, 'label': 2, 'text': 1}
RISK_WORDS = {'LOW': 'bajo', 'MEDIUM': 'moderado medio', 'HIGH': 'alto', 'CRITICAL': 'critico'}
TYPE_WORDS = {'BACHE': 'bache hueco', 'HUNDIMIENTO': 'hundimiento', 'GRIETA': 'grieta', 'OTRO_DANO': 'dano vial'}
STATUS_WORDS = {'UNVERIFIED': 'sin verificar', 'CONFIRMED': 'confirmado', 'IN_PROGRESS': 'en reparacion',
                'REPAIRED': 'reparado', 'REJECTED': 'rechazado'}


class Tokenizer:
    MIN_LENGTH = 2

    @staticmethod
    def normalize(text: str | None) -> str:
        decomposed = unicodedata.normalize('NFKD', (text or '').casefold())
        return ''.join(char for char in decomposed if not unicodedata.combining(char))

    def tokens(self, text: str | None) -> list[str]:
        words = re.findall(r'[a-z0-9]+', self.normalize(text))
        return [word for word in words if len(word) >= self.MIN_LENGTH and word not in STOP_WORDS]


@dataclass
class TrieNode:
    children: dict[str, 'TrieNode'] = field(default_factory=dict)
    entries: dict[str, int] = field(default_factory=dict)  # completion -> weight (documents)


class PrefixTrie:
    def __init__(self):
        self.root = TrieNode()
        self.nodes = 1

    def insert(self, key: str, completion: str, weight: int = 1) -> None:
        """Store ``completion`` under the path ``key``; repeated inserts add weight."""
        node = self.root
        for char in key:
            child = node.children.get(char)
            if child is None:
                child = node.children[char] = TrieNode()
                self.nodes += 1
            node = child
        node.entries[completion] = node.entries.get(completion, 0) + weight

    def _find(self, prefix: str) -> TrieNode | None:
        node = self.root
        for char in prefix:
            node = node.children.get(char)
            if node is None:
                return None
        return node

    def collect(self, prefix: str) -> dict[str, int]:
        """Every completion below ``prefix`` with its weight (iterative DFS with the project Stack)."""
        start = self._find(prefix)
        result: dict[str, int] = {}
        if start is None:
            return result
        pending = Stack[TrieNode]()
        pending.push(start)
        while pending.size:
            node = pending.pop()
            for completion, weight in node.entries.items():
                # A place can be stored under several word starts; count its reports once.
                result[completion] = max(result.get(completion, 0), weight)
            for child in node.children.values():
                pending.push(child)
        return result

    def complete(self, prefix: str, limit: int) -> list[tuple[str, int]]:
        """Heaviest completions for ``prefix``; ties sorted alphabetically."""
        return IndexedMaxHeap(self.collect(prefix).items()).top(limit)


class InvertedIndex:
    def __init__(self):
        self.postings: dict[str, set[str]] = {}

    def add(self, document: str, tokens: set[str]) -> None:
        for token in tokens:
            self.postings.setdefault(token, set()).add(document)

    def documents(self, token: str) -> set[str]:
        return self.postings.get(token, set())

    @staticmethod
    def intersect(sets: list[set[str]]) -> set[str]:
        if not sets:
            return set()
        ordered = sorted(sets, key=len)  # Start with the smallest set: fewer membership checks.
        result = set(ordered[0])
        for other in ordered[1:]:
            result &= other
            if not result:
                break
        return result


class ReportSearchIndex:
    """Search structure built from serialized reports (the API JSON)."""

    MAX_PREFIX_EXPANSION = 50

    def __init__(self, reports: list[dict], tokenizer: Tokenizer | None = None):
        self.tokenizer = tokenizer or Tokenizer()
        self.reports = {report['id']: report for report in reports}
        self.index = InvertedIndex()
        self.words = PrefixTrie()
        self.places = PrefixTrie()
        self.fields: dict[str, dict[str, set[str]]] = {}
        self.facets = BitmapIndex()
        self.by_date: AvlTree[tuple[int, str], str] = AvlTree()
        for report in self.reports.values():
            self._add(report)

    def _add(self, report: dict) -> None:
        zone = report.get('zone') or {}
        place_names = [(kind, zone.get(kind)) for kind in ('street', 'neighborhood', 'city') if zone.get(kind)]
        fields = {
            'place': set(self.tokenizer.tokens(' '.join([name for _, name in place_names] + [zone.get('fullAddress') or '']))),
            'label': set(self.tokenizer.tokens(' '.join([RISK_WORDS.get(report.get('hazardLevel'), ''),
                                                          TYPE_WORDS.get(report.get('potholeType') or 'OTRO_DANO', ''),
                                                          STATUS_WORDS.get(report.get('status'), '')]))),
            'text': set(self.tokenizer.tokens(report.get('aiDescription'))),
        }
        self.fields[report['id']] = fields
        self.facets.add(report['id'], {'risk': report.get('hazardLevel'), 'damage': report.get('potholeType') or 'OTRO_DANO',
                                       'status': report.get('status')})
        self.by_date.insert((report['timestamp'], report['id']), report['id'])
        tokens = set().union(*fields.values())
        self.index.add(report['id'], tokens)
        for token in tokens:
            self.words.insert(token, token)
        for kind, name in place_names:
            label = ' '.join(name.split())
            words = self.tokenizer.normalize(label).split()
            # Index every word start so "panam" also suggests "Avenida Panamericana".
            for start in range(len(words)):
                self.places.insert(' '.join(words[start:]), f'{kind}|{label}')

    def search(self, query: str) -> tuple[list[dict], list[str]]:
        result = self.filter(query)
        return result['reports'], result['tokens']

    def filter(self, query: str | None = None, risk: list[str] | None = None, damage: list[str] | None = None,
               since: int | None = None, until: int | None = None) -> dict:
        """Text, category and date filters combined as bitsets, with facet counts.

        Facet counts follow the usual rule of faceted search: the counts of a field
        apply every filter except that field's own, so the user sees how many
        results each choice would give.
        """
        tokens, relevance = [], {}
        base = self.facets.all
        if query is not None:
            tokens, relevance = self._text_matches(query)
            base &= self.facets.of(relevance)
        if since is not None or until is not None:
            low, high = (since if since is not None else 0, ''), (until if until is not None else 2 ** 63, '\uffff')
            base &= self.facets.of(identity for _, identity in self.by_date.range(low, high))
        risk_bits, damage_bits = self.facets.any_of('risk', risk), self.facets.any_of('damage', damage)
        selected = base & risk_bits & damage_bits
        ranked = sorted((-relevance.get(identity, 0), -self.reports[identity]['hazardScore'],
                         -self.reports[identity]['timestamp'], identity) for identity in self.facets.documents(selected))
        return {'reports': [self.reports[item[-1]] for item in ranked], 'tokens': tokens,
                'facets': {'risk': self.facets.counts('risk', base & damage_bits),
                           'damage': self.facets.counts('damage', base & risk_bits)}}

    def _text_matches(self, query: str) -> tuple[list[str], dict[str, int]]:
        """Report id -> relevance for the words of ``query`` (empty when no word is usable)."""
        tokens = self.tokenizer.tokens(query)
        if not tokens:
            return [], {}
        # Every word must match exactly, except the last one, which may still be incomplete.
        alternatives = [{token} for token in tokens[:-1]]
        alternatives.append({word for word, _ in self.words.complete(tokens[-1], self.MAX_PREFIX_EXPANSION)})
        sets = [set().union(*(self.index.documents(word) for word in words)) for words in alternatives]
        relevance = {}
        for identity in self.index.intersect(sets):
            fields = self.fields[identity]
            # A word found in a place name weighs more than one found in the description.
            relevance[identity] = sum(max((weight for name, weight in FIELD_WEIGHTS.items() if words & fields[name]), default=0)
                                      for words in alternatives)
        return tokens, relevance

    def suggest(self, prefix: str, limit: int) -> list[dict]:
        normalized = ' '.join(self.tokenizer.normalize(prefix).split())
        if len(normalized) < Tokenizer.MIN_LENGTH:
            return []
        suggestions = []
        for completion, count in self.places.complete(normalized, limit):
            kind, label = completion.split('|', 1)
            suggestions.append({'label': label, 'kind': kind, 'count': count})
        return suggestions

    def stats(self) -> dict:
        return {'documents': len(self.reports), 'terms': len(self.index.postings),
                'trieNodes': self.words.nodes + self.places.nodes, 'dateTreeHeight': self.by_date.height}
