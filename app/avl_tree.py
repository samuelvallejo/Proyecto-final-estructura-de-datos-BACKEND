"""AVL tree: a self-balancing binary search tree with subtree sizes.

The project's BinarySearchTree is built balanced but can degrade to a list
after updates. An AVL tree keeps the heights of both children of every node
within one by rotating after each insertion or deletion, so its height stays
below 1.44 log2(n) and every operation is O(log n) in the worst case.

Each node also stores the size of its subtree (an order-statistic tree), so
counting the keys in a range does not need to visit them.

Complexities: insert, remove, find, count_range O(log n); range O(log n + k).
"""
from typing import Generic, Iterator, TypeVar

K = TypeVar('K')
V = TypeVar('V')


class AvlNode(Generic[K, V]):
    __slots__ = ('key', 'value', 'left', 'right', 'height', 'size')

    def __init__(self, key: K, value: V):
        self.key, self.value = key, value
        self.left: AvlNode[K, V] | None = None
        self.right: AvlNode[K, V] | None = None
        self.height = 1
        self.size = 1


def _height(node) -> int:
    return node.height if node else 0


def _size(node) -> int:
    return node.size if node else 0


class AvlTree(Generic[K, V]):
    def __init__(self, items=()):
        self.root: AvlNode[K, V] | None = None
        self.rotations = 0
        for key, value in items:
            self.insert(key, value)

    def __len__(self) -> int:
        return _size(self.root)

    @property
    def height(self) -> int:
        """Edges on the longest root-to-leaf path (-1 when empty), like the project's BST."""
        return _height(self.root) - 1

    # -- queries ----------------------------------------------------------------------
    def find(self, key: K) -> V | None:
        node = self.root
        while node is not None:
            if key == node.key:
                return node.value
            node = node.left if key < node.key else node.right
        return None

    def __contains__(self, key: K) -> bool:
        node = self.root
        while node is not None:
            if key == node.key:
                return True
            node = node.left if key < node.key else node.right
        return False

    def range(self, lower: K, upper: K) -> Iterator[tuple[K, V]]:
        """Pairs with lower <= key <= upper in ascending order; subtrees outside are pruned."""
        pending, node = [], self.root
        while pending or node is not None:
            while node is not None:
                if node.key < lower:
                    node = node.right
                else:
                    pending.append(node)
                    node = node.left
            if not pending:
                return
            node = pending.pop()
            if node.key > upper:
                return
            yield node.key, node.value
            node = node.right

    def rank(self, key: K) -> int:
        """Number of keys strictly smaller than ``key``, using subtree sizes. O(log n)."""
        result, node = 0, self.root
        while node is not None:
            if key <= node.key:
                node = node.left
            else:
                result += _size(node.left) + 1
                node = node.right
        return result

    def count_range(self, lower: K, upper: K) -> int:
        """Keys with lower <= key <= upper without visiting them: two rank queries."""
        if upper < lower:
            return 0
        below_upper, node = 0, self.root  # Keys <= upper.
        while node is not None:
            if node.key <= upper:
                below_upper += _size(node.left) + 1
                node = node.right
            else:
                node = node.left
        return below_upper - self.rank(lower)

    def __iter__(self) -> Iterator[tuple[K, V]]:
        pending, node = [], self.root
        while pending or node is not None:
            while node is not None:
                pending.append(node)
                node = node.left
            node = pending.pop()
            yield node.key, node.value
            node = node.right

    # -- updates ----------------------------------------------------------------------
    def insert(self, key: K, value: V) -> None:
        """Add a key or replace its value."""
        self.root = self._insert(self.root, key, value)

    def remove(self, key: K) -> bool:
        before = len(self)
        self.root = self._remove(self.root, key)
        return len(self) < before

    def _insert(self, node, key, value):
        if node is None:
            return AvlNode(key, value)
        if key == node.key:
            node.value = value
            return node
        if key < node.key:
            node.left = self._insert(node.left, key, value)
        else:
            node.right = self._insert(node.right, key, value)
        return self._rebalance(node)

    def _remove(self, node, key):
        if node is None:
            return None
        if key < node.key:
            node.left = self._remove(node.left, key)
        elif node.key < key:
            node.right = self._remove(node.right, key)
        else:
            if node.left is None or node.right is None:
                return node.left or node.right
            successor = node.right
            while successor.left is not None:
                successor = successor.left
            node.key, node.value = successor.key, successor.value
            node.right = self._remove(node.right, successor.key)
        return self._rebalance(node)

    # -- balancing --------------------------------------------------------------------
    @staticmethod
    def _update(node) -> None:
        node.height = 1 + max(_height(node.left), _height(node.right))
        node.size = 1 + _size(node.left) + _size(node.right)

    def _rotate_right(self, node):
        pivot = node.left
        node.left, pivot.right = pivot.right, node
        self._update(node)
        self._update(pivot)
        self.rotations += 1
        return pivot

    def _rotate_left(self, node):
        pivot = node.right
        node.right, pivot.left = pivot.left, node
        self._update(node)
        self._update(pivot)
        self.rotations += 1
        return pivot

    def _rebalance(self, node):
        self._update(node)
        balance = _height(node.left) - _height(node.right)
        if balance > 1:  # Left heavy: LL or LR case.
            if _height(node.left.left) < _height(node.left.right):
                node.left = self._rotate_left(node.left)
            return self._rotate_right(node)
        if balance < -1:  # Right heavy: RR or RL case.
            if _height(node.right.right) < _height(node.right.left):
                node.right = self._rotate_right(node.right)
            return self._rotate_left(node)
        return node

    def validate(self) -> bool:
        """Order, balance factors, heights and sizes are all consistent."""
        def check(node, lower, upper):
            if node is None:
                return True, 0, 0
            if (lower is not None and not lower < node.key) or (upper is not None and not node.key < upper):
                return False, 0, 0
            ok_left, height_left, size_left = check(node.left, lower, node.key)
            ok_right, height_right, size_right = check(node.right, node.key, upper)
            height, size = 1 + max(height_left, height_right), 1 + size_left + size_right
            ok = ok_left and ok_right and abs(height_left - height_right) <= 1 and node.height == height and node.size == size
            return ok, height, size
        return check(self.root, None, None)[0]
