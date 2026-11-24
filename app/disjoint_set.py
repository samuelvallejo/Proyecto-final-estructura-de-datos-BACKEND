"""Disjoint-set forest (union-find) with path compression and union by rank.

Each element points to a parent; the root of a tree represents its whole set.
With both optimizations ``find`` and ``union`` cost O(alpha(n)) amortized, where
alpha is the inverse Ackermann function (at most 4 for any practical n).
"""
from typing import Generic, Hashable, Iterable, TypeVar

T = TypeVar('T', bound=Hashable)


class DisjointSet(Generic[T]):
    def __init__(self, items: Iterable[T] = ()):
        self._parent: dict[T, T] = {}
        self._rank: dict[T, int] = {}
        self._size: dict[T, int] = {}
        self.sets = 0
        for item in items:
            self.add(item)

    def __len__(self) -> int:
        return len(self._parent)

    def __contains__(self, item: T) -> bool:
        return item in self._parent

    def add(self, item: T) -> bool:
        """Create the singleton set {item}; False if the item already exists."""
        if item in self._parent:
            return False
        self._parent[item] = item
        self._rank[item] = 0
        self._size[item] = 1
        self.sets += 1
        return True

    def find(self, item: T) -> T:
        """Representative of the item's set. Iterative two-pass path compression."""
        if item not in self._parent:
            raise KeyError('Unknown element')
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, first: T, second: T) -> bool:
        """Join both sets; False when they were already the same set."""
        a, b = self.find(first), self.find(second)
        if a == b:
            return False
        if self._rank[a] < self._rank[b]:
            a, b = b, a
        self._parent[b] = a  # The shallower tree hangs from the deeper one.
        self._size[a] += self._size.pop(b)
        if self._rank[a] == self._rank[b]:
            self._rank[a] += 1
        del self._rank[b]
        self.sets -= 1
        return True

    def connected(self, first: T, second: T) -> bool:
        return self.find(first) == self.find(second)

    def size_of(self, item: T) -> int:
        return self._size[self.find(item)]

    def groups(self) -> list[list[T]]:
        """Every set as a list, in insertion order of its first element."""
        grouped: dict[T, list[T]] = {}
        for item in self._parent:
            grouped.setdefault(self.find(item), []).append(item)
        return list(grouped.values())
