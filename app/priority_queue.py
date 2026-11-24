"""Indexed binary max-heap stored in an array.

A plain binary heap cannot find an arbitrary element, so updating or removing
one costs O(n). This heap keeps a hash map ``key -> array index`` that is
updated on every swap, which makes ``update`` and ``remove`` O(log n).

Ordering: a higher priority comes first. Equal priorities are broken by the
smaller key so the result is deterministic for the same input.

Complexities (n = size, k = requested elements):
    heapify (constructor)  O(n)
    push / pop / update    O(log n)
    remove                 O(log n)
    peek / contains        O(1)
    top(k) without pop     O(k log k)
Space: O(n) for the array plus O(n) for the index map.
"""
from typing import Generic, Hashable, Iterable, Iterator, TypeVar

K = TypeVar('K', bound=Hashable)
P = TypeVar('P')


class HeapEntry(Generic[K, P]):
    """One element of the heap: a unique key and its comparable priority."""

    __slots__ = ('key', 'priority')

    def __init__(self, key: K, priority: P):
        self.key = key
        self.priority = priority

    def outranks(self, other: 'HeapEntry[K, P]') -> bool:
        """True when this entry must be closer to the root than ``other``."""
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.key < other.key

    def as_tuple(self) -> tuple[K, P]:
        return self.key, self.priority


class IndexedMaxHeap(Generic[K, P]):
    def __init__(self, items: Iterable[tuple[K, P]] = ()):
        self._entries: list[HeapEntry[K, P]] = []
        self._position: dict[K, int] = {}
        self.comparisons = 0  # Priority comparisons performed; used to measure the cost.
        for key, priority in items:
            if key in self._position:
                raise KeyError('Duplicated heap key')
            self._position[key] = len(self._entries)
            self._entries.append(HeapEntry(key, priority))
        self._heapify()

    # -- public API -----------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __contains__(self, key: K) -> bool:
        return key in self._position

    @property
    def height(self) -> int:
        """Edges from the root to the deepest leaf of the complete tree (-1 when empty)."""
        return len(self._entries).bit_length() - 1

    def priority_of(self, key: K) -> P:
        return self._entries[self._position[key]].priority

    def peek(self) -> tuple[K, P]:
        if not self._entries:
            raise IndexError('Empty heap')
        return self._entries[0].as_tuple()

    def push(self, key: K, priority: P) -> None:
        if key in self._position:
            raise KeyError('Duplicated heap key')
        self._entries.append(HeapEntry(key, priority))
        self._position[key] = len(self._entries) - 1
        self._sift_up(len(self._entries) - 1)

    def pop(self) -> tuple[K, P]:
        if not self._entries:
            raise IndexError('Empty heap')
        return self._remove_at(0).as_tuple()

    def update(self, key: K, priority: P) -> None:
        """Change the priority of an existing key and restore the heap order."""
        index = self._position[key]
        self._entries[index].priority = priority
        self._restore(index)

    def remove(self, key: K) -> bool:
        index = self._position.get(key)
        if index is None:
            return False
        self._remove_at(index)
        return True

    def top(self, limit: int) -> list[tuple[K, P]]:
        """The ``limit`` highest entries in order, without modifying this heap.

        Only the children of already selected nodes can be the next maximum, so a
        second (small) heap acts as the frontier: O(limit log limit) instead of
        copying and popping the whole structure.
        """
        if limit <= 0 or not self._entries:
            return []
        frontier: IndexedMaxHeap[K, P] = IndexedMaxHeap()
        root = self._entries[0]
        frontier.push(root.key, root.priority)
        result = []
        while frontier and len(result) < limit:
            key, priority = frontier.pop()
            result.append((key, priority))
            index = self._position[key]
            for child in (2 * index + 1, 2 * index + 2):
                if child < len(self._entries):
                    entry = self._entries[child]
                    frontier.push(entry.key, entry.priority)
        return result

    def drain(self) -> Iterator[tuple[K, P]]:
        """Pop every element in priority order (destructive heap sort)."""
        while self._entries:
            yield self.pop()

    def validate(self) -> bool:
        """Check the heap property and that the index map matches the array."""
        if len(self._position) != len(self._entries):
            return False
        for index, entry in enumerate(self._entries):
            if self._position.get(entry.key) != index:
                return False
            for child in (2 * index + 1, 2 * index + 2):
                if child < len(self._entries) and self._entries[child].outranks(entry):
                    return False
        return True

    # -- internal operations --------------------------------------------------------
    def _heapify(self) -> None:
        # Floyd's bottom-up construction: sift down every internal node, O(n).
        for index in range(len(self._entries) // 2 - 1, -1, -1):
            self._sift_down(index)

    def _outranks(self, first: int, second: int) -> bool:
        self.comparisons += 1
        return self._entries[first].outranks(self._entries[second])

    def _swap(self, first: int, second: int) -> None:
        entries = self._entries
        entries[first], entries[second] = entries[second], entries[first]
        self._position[entries[first].key] = first
        self._position[entries[second].key] = second

    def _sift_up(self, index: int) -> None:
        while index > 0:
            parent = (index - 1) // 2
            if not self._outranks(index, parent):
                break
            self._swap(index, parent)
            index = parent

    def _sift_down(self, index: int) -> None:
        size = len(self._entries)
        while True:
            best = index
            for child in (2 * index + 1, 2 * index + 2):
                if child < size and self._outranks(child, best):
                    best = child
            if best == index:
                return
            self._swap(index, best)
            index = best

    def _restore(self, index: int) -> None:
        if index > 0 and self._outranks(index, (index - 1) // 2):
            self._sift_up(index)
        else:
            self._sift_down(index)

    def _remove_at(self, index: int) -> HeapEntry[K, P]:
        last = len(self._entries) - 1
        if index != last:
            self._swap(index, last)
        entry = self._entries.pop()
        del self._position[entry.key]
        if index < len(self._entries):
            self._restore(index)
        return entry
