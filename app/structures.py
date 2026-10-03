"""Estructuras explícitas: los nodos enlazados no se sustituyen por list/deque."""
from dataclasses import dataclass
from typing import Generic, Iterator, TypeVar

T = TypeVar('T')


@dataclass
class Node(Generic[T]):
    value: T
    next: 'Node[T] | None' = None
    prev: 'Node[T] | None' = None


class SinglyLinkedList(Generic[T]):
    def __init__(self):
        self.head = self.tail = None
        self.size = 0

    def append(self, value: T):
        node = Node(value)
        if self.tail is None:
            self.head = node
        else:
            self.tail.next = node
        self.tail = node
        self.size += 1

    def popleft(self) -> T:
        if self.head is None:
            raise IndexError('Lista vacía')
        node = self.head
        self.head = node.next
        self.size -= 1
        if not self.size:
            self.tail = None
        return node.value

    def __iter__(self) -> Iterator[T]:
        node = self.head
        while node is not None:
            yield node.value
            node = node.next


class DoublyLinkedList(SinglyLinkedList[T]):
    def append(self, value: T):
        previous = self.tail
        super().append(value)
        self.tail.prev = previous

    def popleft(self) -> T:
        value = super().popleft()
        if self.head is not None:
            self.head.prev = None
        return value

    def pop(self) -> T:
        if self.tail is None:
            raise IndexError('Lista vacía')
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
    def __init__(self):
        self.tail = None
        self.cursor = None
        self.size = 0

    def append(self, value: T):
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
        if self.cursor is None:
            raise IndexError('Lista vacía')
        value = self.cursor.value
        self.cursor = self.cursor.next
        return value

    def __iter__(self) -> Iterator[T]:
        node = self.tail.next if self.tail else None
        for _ in range(self.size):
            yield node.value
            node = node.next


class CircularDoublyLinkedList(CircularSinglyLinkedList[T]):
    def append(self, value: T):
        previous = self.tail
        super().append(value)
        if previous is None:
            self.tail.prev = self.tail
        else:
            self.tail.prev = previous
            self.tail.next.prev = self.tail

    def retreat(self) -> T:
        if self.cursor is None:
            raise IndexError('Lista vacía')
        self.cursor = self.cursor.prev
        return self.cursor.value


class Stack(Generic[T]):
    def __init__(self):
        self.items: list[T] = []  # Array dinámico; acceso al extremo O(1) amortizado.

    def push(self, value: T):
        self.items.append(value)

    def pop(self) -> T:
        if not self.items:
            raise IndexError('Pila vacía')
        return self.items.pop()

    @property
    def size(self):
        return len(self.items)


class Queue(Generic[T]):
    def __init__(self):
        self.items = SinglyLinkedList[T]()

    def enqueue(self, value: T):
        self.items.append(value)

    def dequeue(self) -> T:
        return self.items.popleft()

    @property
    def size(self):
        return self.items.size


class Deque(Generic[T]):
    def __init__(self):
        self.items = DoublyLinkedList[T]()

    def append(self, value: T):
        self.items.append(value)

    def appendleft(self, value: T):
        node = Node(value, next=self.items.head)
        if self.items.head:
            self.items.head.prev = node
        else:
            self.items.tail = node
        self.items.head = node
        self.items.size += 1

    def popleft(self) -> T:
        return self.items.popleft()

    def pop(self) -> T:
        return self.items.pop()

    @property
    def size(self):
        return self.items.size
