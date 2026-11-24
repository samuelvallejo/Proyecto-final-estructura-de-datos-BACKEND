"""Binary search tree adapted from the Node/BinaryTree examples of the course notes (Arboles.pdf).

Left/right links are real nodes. It is not self-balancing (not an AVL): snapshots are built
balanced from sorted data and later operations follow plain BST rules. Every traversal uses the
hand-written Stack and Queue from ``structures`` instead of Python lists.
"""
from __future__ import annotations

from typing import Generic, Iterable, Iterator, TypeVar

from .structures import DynamicArray, HashSet, Queue, SinglyLinkedList, Sorter, Stack

K = TypeVar('K')
V = TypeVar('V')


class TreeNode(Generic[K, V]):
    __slots__ = ('key', 'value', 'left', 'right')

    def __init__(self, key: K, value: V, left: TreeNode[K, V] | None = None, right: TreeNode[K, V] | None = None):
        self.key = key
        self.value = value
        self.left = left
        self.right = right


class BinarySearchTree(Generic[K, V]):
    def __init__(self):
        self.root: TreeNode[K, V] | None = None
        self.size = 0

    def insert(self, key: K, value: V) -> bool:
        """Insert ``key``; an existing key only updates its value and returns False."""
        if self.root is None:
            self.root = TreeNode(key, value)
            self.size = 1
            return True
        current = self.root
        while True:
            if key == current.key:
                current.value = value
                return False
            if key < current.key:
                if current.left is None:
                    current.left = TreeNode(key, value)
                    self.size += 1
                    return True
                current = current.left
            else:
                if current.right is None:
                    current.right = TreeNode(key, value)
                    self.size += 1
                    return True
                current = current.right

    def find_node(self, key: K) -> TreeNode[K, V] | None:
        current = self.root
        while current is not None:
            if key == current.key:
                return current
            current = current.left if key < current.key else current.right
        return None

    def search(self, key: K) -> V | None:
        node = self.find_node(key)
        return node.value if node is not None else None

    def contains(self, key: K) -> bool:
        return self.find_node(key) is not None

    def in_order(self) -> Iterator[TreeNode[K, V]]:
        pending = Stack[TreeNode[K, V]]()
        current = self.root
        while current is not None or not pending.is_empty():
            while current is not None:
                pending.push(current)
                current = current.left
            current = pending.pop()
            yield current
            current = current.right

    def reverse_order(self) -> Iterator[TreeNode[K, V]]:
        pending = Stack[TreeNode[K, V]]()
        current = self.root
        while current is not None or not pending.is_empty():
            while current is not None:
                pending.push(current)
                current = current.right
            current = pending.pop()
            yield current
            current = current.left

    def pre_order(self) -> Iterator[TreeNode[K, V]]:
        pending = Stack[TreeNode[K, V]]()
        if self.root is not None:
            pending.push(self.root)
        while not pending.is_empty():
            node = pending.pop()
            yield node
            if node.right is not None:
                pending.push(node.right)
            if node.left is not None:
                pending.push(node.left)

    def post_order(self) -> Iterator[TreeNode[K, V]]:
        pending = Stack[tuple]()
        if self.root is not None:
            pending.push((self.root, False))
        while not pending.is_empty():
            node, visited = pending.pop()
            if visited:
                yield node
                continue
            pending.push((node, True))
            if node.right is not None:
                pending.push((node.right, False))
            if node.left is not None:
                pending.push((node.left, False))

    def level_order(self) -> Iterator[tuple[TreeNode[K, V], int, TreeNode[K, V] | None]]:
        pending = Queue[tuple]()
        if self.root is not None:
            pending.enqueue((self.root, 1, None))
        while not pending.is_empty():
            node, level, parent = pending.dequeue()
            yield node, level, parent
            if node.left is not None:
                pending.enqueue((node.left, level + 1, node))
            if node.right is not None:
                pending.enqueue((node.right, level + 1, node))

    def traverse(self, order: str = 'inorder') -> Iterator[TreeNode[K, V]]:
        if order == 'level':
            return (node for node, _, _ in self.level_order())
        if order == 'inorder':
            return self.in_order()
        if order == 'descending':
            return self.reverse_order()
        if order == 'preorder':
            return self.pre_order()
        if order == 'postorder':
            return self.post_order()
        raise ValueError('Invalid traversal')

    @property
    def height(self) -> int:
        return max((level - 1 for _, level, _ in self.level_order()), default=-1)

    def metrics(self) -> dict:
        leaves = branches = maximum_degree = 0
        for node, _, parent in self.level_order():
            degree = int(node.left is not None) + int(node.right is not None)
            maximum_degree = max(maximum_degree, degree)
            leaves += degree == 0
            branches += parent is not None and degree > 0
        return {'weight': self.size, 'height': self.height, 'levels': self.height + 1,
                'leaves': leaves, 'branches': branches, 'internalNodes': self.size - leaves,
                'order': 2, 'maxDegree': maximum_degree}

    def trace(self, key: K) -> SinglyLinkedList[TreeNode[K, V]]:
        """Nodes visited while searching ``key``, from the root down."""
        path = SinglyLinkedList[TreeNode[K, V]]()
        current = self.root
        while current is not None:
            path.append(current)
            if key == current.key:
                break
            current = current.left if key < current.key else current.right
        return path

    def between(self, lower: K, upper: K) -> Iterator[TreeNode[K, V]]:
        """In-order nodes with ``lower <= key <= upper``, pruning subtrees outside the range."""
        if upper < lower:
            raise ValueError('Invalid range')
        pending = Stack[TreeNode[K, V]]()
        current = self.root
        while current is not None or not pending.is_empty():
            while current is not None:
                if current.key < lower:
                    current = current.right
                else:
                    pending.push(current)
                    current = current.left
            if pending.is_empty():
                break
            current = pending.pop()
            if current.key > upper:
                break
            yield current
            current = current.right

    def remove(self, key: K) -> bool:
        parent = None
        current = self.root
        while current is not None and current.key != key:
            parent = current
            current = current.left if key < current.key else current.right
        if current is None:
            return False
        if current.left is not None and current.right is not None:
            # Two children: copy the in-order successor and delete it instead.
            successor_parent, successor = current, current.right
            while successor.left is not None:
                successor_parent, successor = successor, successor.left
            current.key, current.value = successor.key, successor.value
            parent, current = successor_parent, successor
        child = current.left if current.left is not None else current.right
        if parent is None:
            self.root = child
        elif parent.left is current:
            parent.left = child
        else:
            parent.right = child
        self.size -= 1
        return True

    @classmethod
    def from_items(cls, items: Iterable[tuple[K, V]]) -> BinarySearchTree[K, V]:
        """Build a balanced tree: sort, keep the last value of repeated keys, split at the middle."""
        unique = DynamicArray[tuple]()
        for pair in Sorter.merge_sort(items, key=lambda pair: pair[0]):
            if unique.size and unique[-1][0] == pair[0]:
                unique[-1] = pair  # Like the course's phone book: a repeated key updates the value.
            else:
                unique.append(pair)
        tree = cls()
        tasks = Stack[tuple]()
        tasks.push((0, unique.size, None, 'root'))
        while not tasks.is_empty():
            first, last, parent, side = tasks.pop()
            if first >= last:
                continue
            middle = (first + last) // 2
            node = TreeNode(*unique[middle])
            if parent is None:
                tree.root = node
            elif side == 'left':
                parent.left = node
            else:
                parent.right = node
            tree.size += 1
            tasks.push((middle + 1, last, node, 'right'))
            tasks.push((first, middle, node, 'left'))
        return tree

    def rebalance(self) -> None:
        rebuilt = self.from_items((node.key, node.value) for node in self.in_order())
        self.root, self.size = rebuilt.root, rebuilt.size

    def validate(self) -> bool:
        """Check BST ordering, absence of cycles and that ``size`` matches the real node count."""
        seen = HashSet[int]()
        pending = Stack[tuple]()
        if self.root is not None:
            pending.push((self.root, None, None))
        while not pending.is_empty():
            node, lower, upper = pending.pop()
            if id(node) in seen or (lower is not None and node.key <= lower) or (upper is not None and node.key >= upper):
                return False
            seen.add(id(node))
            if node.right is not None:
                pending.push((node.right, node.key, upper))
            if node.left is not None:
                pending.push((node.left, lower, node.key))
        return len(seen) == self.size

    def clear(self) -> None:
        self.root = None
        self.size = 0

    def __len__(self) -> int:
        return self.size

    def __bool__(self) -> bool:
        return self.root is not None
