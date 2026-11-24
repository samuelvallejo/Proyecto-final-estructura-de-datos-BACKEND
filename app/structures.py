"""Hand-written data structures used across BacheScan.

Every structure here is implemented from scratch with its own nodes or arrays. Python's
built-in list, dict, set, deque and heapq are not used to model them; the only primitive
is a fixed-size array (``[None] * capacity``), the same building block a C array provides.
"""
from __future__ import annotations

from typing import Callable, Generic, Iterable, Iterator, TypeVar

T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')


class Node(Generic[T]):
    """Linked-list node with optional backward link (used by doubly linked lists)."""
    __slots__ = ('value', 'next', 'prev')

    def __init__(self, value: T, next: Node[T] | None = None, prev: Node[T] | None = None):
        self.value = value
        self.next = next
        self.prev = prev


class SinglyLinkedList(Generic[T]):
    """Singly linked list with head and tail pointers: O(1) append, prepend and pop-left."""

    def __init__(self, values: Iterable[T] = ()):
        self.head: Node[T] | None = None
        self.tail: Node[T] | None = None
        self.size = 0
        for value in values:
            self.append(value)

    def append(self, value: T) -> None:
        node = Node(value)
        if self.tail is None:
            self.head = node
        else:
            self.tail.next = node
        self.tail = node
        self.size += 1

    def prepend(self, value: T) -> None:
        node = Node(value, next=self.head)
        self.head = node
        if self.tail is None:
            self.tail = node
        self.size += 1

    def popleft(self) -> T:
        if self.head is None:
            raise IndexError('Empty list')
        node = self.head
        self.head = node.next
        self.size -= 1
        if not self.size:
            self.tail = None
        return node.value

    def remove_first(self, predicate: Callable[[T], bool]) -> T | None:
        """Remove and return the first value matching ``predicate`` (O(n))."""
        previous, current = None, self.head
        while current is not None:
            if predicate(current.value):
                if previous is None:
                    self.head = current.next
                else:
                    previous.next = current.next
                if current is self.tail:
                    self.tail = previous
                self.size -= 1
                return current.value
            previous, current = current, current.next
        return None

    def find(self, predicate: Callable[[T], bool]) -> T | None:
        for value in self:
            if predicate(value):
                return value
        return None

    def is_empty(self) -> bool:
        return self.size == 0

    def __getitem__(self, index: int) -> T:
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError('Index out of range')
        node = self.head
        for _ in range(index):
            node = node.next
        return node.value

    def __len__(self) -> int:
        return self.size

    def __bool__(self) -> bool:
        return self.size > 0

    def __iter__(self) -> Iterator[T]:
        node = self.head
        while node is not None:
            yield node.value
            node = node.next


class DoublyLinkedList(SinglyLinkedList[T]):
    """Doubly linked list: O(1) insertion and removal at both ends and reverse iteration."""

    def append(self, value: T) -> None:
        previous = self.tail
        super().append(value)
        self.tail.prev = previous

    def prepend(self, value: T) -> None:
        super().prepend(value)
        if self.head.next is not None:
            self.head.next.prev = self.head

    def popleft(self) -> T:
        value = super().popleft()
        if self.head is not None:
            self.head.prev = None
        return value

    def pop(self) -> T:
        if self.tail is None:
            raise IndexError('Empty list')
        node = self.tail
        self.tail = node.prev
        if self.tail is None:
            self.head = None
        else:
            self.tail.next = None
        self.size -= 1
        return node.value

    def reverse(self) -> Iterator[T]:
        node = self.tail
        while node is not None:
            yield node.value
            node = node.prev


class CircularSinglyLinkedList(Generic[T]):
    """Circular singly linked list with a moving cursor (round robin)."""

    def __init__(self):
        self.tail: Node[T] | None = None
        self.cursor: Node[T] | None = None
        self.size = 0

    def append(self, value: T) -> None:
        node = Node(value)
        if self.tail is None:
            node.next = node
            self.cursor = node
        else:
            node.next = self.tail.next
            self.tail.next = node
        self.tail = node
        self.size += 1

    def advance(self) -> T:
        """Return the value under the cursor and move the cursor forward."""
        if self.cursor is None:
            raise IndexError('Empty list')
        value = self.cursor.value
        self.cursor = self.cursor.next
        return value

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[T]:
        node = self.tail.next if self.tail else None
        for _ in range(self.size):
            yield node.value
            node = node.next


class CircularDoublyLinkedList(CircularSinglyLinkedList[T]):
    """Circular doubly linked list: the cursor can move forward and backward."""

    def append(self, value: T) -> None:
        previous = self.tail
        super().append(value)
        if previous is None:
            self.tail.prev = self.tail
        else:
            self.tail.prev = previous
            self.tail.next.prev = self.tail

    def retreat(self) -> T:
        """Move the cursor backward and return its value."""
        if self.cursor is None:
            raise IndexError('Empty list')
        self.cursor = self.cursor.prev
        return self.cursor.value


class Stack(Generic[T]):
    """LIFO stack on linked nodes: push and pop at the head in O(1)."""

    def __init__(self):
        self._top: Node[T] | None = None
        self.size = 0

    def push(self, value: T) -> None:
        self._top = Node(value, next=self._top)
        self.size += 1

    def pop(self) -> T:
        if self._top is None:
            raise IndexError('Empty stack')
        node = self._top
        self._top = node.next
        self.size -= 1
        return node.value

    def peek(self) -> T:
        if self._top is None:
            raise IndexError('Empty stack')
        return self._top.value

    def is_empty(self) -> bool:
        return self._top is None

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[T]:
        """Iterate from the top of the stack to the bottom."""
        node = self._top
        while node is not None:
            yield node.value
            node = node.next


class Queue(Generic[T]):
    """FIFO queue backed by a singly linked list: enqueue at the tail, dequeue at the head."""

    def __init__(self):
        self.items = SinglyLinkedList[T]()

    def enqueue(self, value: T) -> None:
        self.items.append(value)

    def dequeue(self) -> T:
        return self.items.popleft()

    def peek(self) -> T:
        if self.items.head is None:
            raise IndexError('Empty queue')
        return self.items.head.value

    def is_empty(self) -> bool:
        return self.items.size == 0

    @property
    def size(self) -> int:
        return self.items.size

    def __len__(self) -> int:
        return self.items.size


class Deque(Generic[T]):
    """Double-ended queue backed by a doubly linked list."""

    def __init__(self):
        self.items = DoublyLinkedList[T]()

    def append(self, value: T) -> None:
        self.items.append(value)

    def appendleft(self, value: T) -> None:
        self.items.prepend(value)

    def popleft(self) -> T:
        return self.items.popleft()

    def pop(self) -> T:
        return self.items.pop()

    @property
    def size(self) -> int:
        return self.items.size

    def __len__(self) -> int:
        return self.items.size

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)


class DynamicArray(Generic[T]):
    """Growable array over a fixed-size block that doubles its capacity when full."""

    def __init__(self, values: Iterable[T] = (), capacity: int = 8):
        self._capacity = max(1, capacity)
        self._data = [None] * self._capacity
        self.size = 0
        for value in values:
            self.append(value)

    def _check(self, index: int) -> int:
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError('Index out of range')
        return index

    def _grow(self) -> None:
        bigger = [None] * (self._capacity * 2)
        for index in range(self.size):
            bigger[index] = self._data[index]
        self._data, self._capacity = bigger, self._capacity * 2

    def append(self, value: T) -> None:
        if self.size == self._capacity:
            self._grow()
        self._data[self.size] = value
        self.size += 1

    def pop(self) -> T:
        if not self.size:
            raise IndexError('Empty array')
        self.size -= 1
        value = self._data[self.size]
        self._data[self.size] = None
        return value

    def swap(self, first: int, second: int) -> None:
        self._data[first], self._data[second] = self._data[second], self._data[first]

    def __getitem__(self, index: int) -> T:
        return self._data[self._check(index)]

    def __setitem__(self, index: int, value: T) -> None:
        self._data[self._check(index)] = value

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[T]:
        for index in range(self.size):
            yield self._data[index]


class MinHeap(Generic[T]):
    """Binary min-heap over a DynamicArray; each item is a ``(priority, value)`` pair."""

    def __init__(self):
        self._items = DynamicArray[tuple]()

    def push(self, priority, value: T) -> None:
        self._items.append((priority, value))
        child = self._items.size - 1
        while child > 0:
            parent = (child - 1) // 2
            if self._items[child][0] >= self._items[parent][0]:
                break
            self._items.swap(child, parent)
            child = parent

    def pop(self) -> tuple:
        if not self._items.size:
            raise IndexError('Empty heap')
        top = self._items[0]
        last = self._items.pop()
        if self._items.size:
            self._items[0] = last
            parent = 0
            while True:
                left, right, smallest = 2 * parent + 1, 2 * parent + 2, parent
                if left < self._items.size and self._items[left][0] < self._items[smallest][0]:
                    smallest = left
                if right < self._items.size and self._items[right][0] < self._items[smallest][0]:
                    smallest = right
                if smallest == parent:
                    break
                self._items.swap(parent, smallest)
                parent = smallest
        return top

    @property
    def size(self) -> int:
        return self._items.size

    def __len__(self) -> int:
        return self._items.size


class _Entry(Generic[K, V]):
    __slots__ = ('key', 'value')

    def __init__(self, key: K, value: V):
        self.key = key
        self.value = value


class HashMap(Generic[K, V]):
    """Hash table with separate chaining: each bucket is a singly linked list of entries.

    Doubles its bucket array when the load factor passes 0.75, so lookups stay O(1) on average.
    """

    def __init__(self, items: Iterable[tuple[K, V]] = (), capacity: int = 16):
        self._buckets = [None] * capacity
        self.size = 0
        for key, value in items:
            self.put(key, value)

    def _bucket(self, key: K) -> SinglyLinkedList[_Entry[K, V]]:
        index = hash(key) % len(self._buckets)
        bucket = self._buckets[index]
        if bucket is None:
            bucket = self._buckets[index] = SinglyLinkedList()
        return bucket

    def _resize(self) -> None:
        old = self._buckets
        self._buckets = [None] * (len(old) * 2)
        self.size = 0
        for bucket in old:
            if bucket is not None:
                for entry in bucket:
                    self.put(entry.key, entry.value)

    def put(self, key: K, value: V) -> None:
        bucket = self._bucket(key)
        entry = bucket.find(lambda item: item.key == key)
        if entry is not None:
            entry.value = value
            return
        bucket.append(_Entry(key, value))
        self.size += 1
        if self.size > len(self._buckets) * .75:
            self._resize()

    def get(self, key: K, default: V | None = None) -> V | None:
        entry = self._bucket(key).find(lambda item: item.key == key)
        return entry.value if entry is not None else default

    def remove(self, key: K) -> V | None:
        entry = self._bucket(key).remove_first(lambda item: item.key == key)
        if entry is None:
            return None
        self.size -= 1
        return entry.value

    def setdefault(self, key: K, factory: Callable[[], V]) -> V:
        """Return the value for ``key``, creating it with ``factory()`` when missing."""
        entry = self._bucket(key).find(lambda item: item.key == key)
        if entry is not None:
            return entry.value
        value = factory()
        self.put(key, value)
        return value

    def contains(self, key: K) -> bool:
        return self._bucket(key).find(lambda item: item.key == key) is not None

    def entries(self) -> Iterator[_Entry[K, V]]:
        for bucket in self._buckets:
            if bucket is not None:
                yield from bucket

    def keys(self) -> Iterator[K]:
        return (entry.key for entry in self.entries())

    def values(self) -> Iterator[V]:
        return (entry.value for entry in self.entries())

    def items(self) -> Iterator[tuple[K, V]]:
        return ((entry.key, entry.value) for entry in self.entries())

    def __getitem__(self, key: K) -> V:
        entry = self._bucket(key).find(lambda item: item.key == key)
        if entry is None:
            raise KeyError(key)
        return entry.value

    def __setitem__(self, key: K, value: V) -> None:
        self.put(key, value)

    def __contains__(self, key: K) -> bool:
        return self.contains(key)

    def __len__(self) -> int:
        return self.size

    def __iter__(self) -> Iterator[K]:
        return self.keys()


class HashSet(Generic[T]):
    """Set of unique values backed by HashMap (the value of every entry is ``True``)."""

    def __init__(self, values: Iterable[T] = ()):
        self._map = HashMap[T, bool]()
        for value in values:
            self.add(value)

    def add(self, value: T) -> None:
        self._map.put(value, True)

    def remove(self, value: T) -> None:
        self._map.remove(value)

    def __contains__(self, value: T) -> bool:
        return self._map.contains(value)

    def __len__(self) -> int:
        return self._map.size

    def __iter__(self) -> Iterator[T]:
        return self._map.keys()


class Sorter:
    """Stable merge sort on linked lists: O(n log n), no built-in ``sorted``."""

    @staticmethod
    def merge_sort(values: Iterable[T], key: Callable[[T], object] = lambda value: value,
                   reverse: bool = False) -> SinglyLinkedList[T]:
        source = SinglyLinkedList(values)  # Always a copy: the caller's structure is never reordered.
        result = SinglyLinkedList[T]()
        result.head = Sorter._sort(source.head, key, reverse)
        result.size = source.size
        node = result.head
        while node is not None and node.next is not None:
            node = node.next
        result.tail = node
        return result

    @staticmethod
    def _before(left, right, key, reverse) -> bool:
        # Equal keys keep their original order, so the sort is stable in both directions.
        a, b = key(left), key(right)
        return not (b > a) if reverse else not (b < a)

    @staticmethod
    def _sort(head, key, reverse):
        if head is None or head.next is None:
            return head
        slow, fast = head, head.next
        while fast is not None and fast.next is not None:
            slow, fast = slow.next, fast.next.next
        second, slow.next = slow.next, None
        left, right = Sorter._sort(head, key, reverse), Sorter._sort(second, key, reverse)
        dummy = tail = Node(None)
        while left is not None and right is not None:
            if Sorter._before(left.value, right.value, key, reverse):
                tail.next, left = left, left.next
            else:
                tail.next, right = right, right.next
            tail = tail.next
        tail.next = left if left is not None else right
        return dummy.next
