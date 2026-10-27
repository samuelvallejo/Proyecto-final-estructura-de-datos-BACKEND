"""Adaptación de Node/BinaryTree de Arboles.pdf (Mideros, 2026).

Los enlaces left/right son nodos reales. No es un AVL: las instantáneas
se construyen equilibradas y las operaciones posteriores siguen siendo BST.
"""
from dataclasses import dataclass
from typing import Generic, Iterator, TypeVar
from .structures import Queue

K = TypeVar('K')
V = TypeVar('V')

@dataclass
class TreeNode(Generic[K, V]):
    key: K
    value: V
    left: 'TreeNode[K, V] | None' = None
    right: 'TreeNode[K, V] | None' = None


class BinarySearchTree(Generic[K, V]):
    def __init__(self):
        self.root: TreeNode[K, V] | None = None
        self.size = 0

    def insert(self, key: K, value: V) -> bool:
        if self.root is None:
            self.root = TreeNode(key, value)
            self.size = 1
            return True
        current = self.root
        while True:
            if key == current.key:
                current.value = value
                return False
            side = 'left' if key < current.key else 'right'
            child = getattr(current, side)
            if child is None:
                setattr(current, side, TreeNode(key, value))
                self.size += 1
                return True
            current = child

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
        pending = []
        current = self.root
        while current is not None or pending:
            while current is not None:
                pending.append(current)
                current = current.left
            current = pending.pop()
            yield current
            current = current.right

    def reverse_order(self) -> Iterator[TreeNode[K, V]]:
        pending = []
        current = self.root
        while current is not None or pending:
            while current is not None:
                pending.append(current)
                current = current.right
            current = pending.pop()
            yield current
            current = current.left

    def pre_order(self) -> Iterator[TreeNode[K, V]]:
        pending = [self.root] if self.root else []
        while pending:
            node = pending.pop()
            yield node
            if node.right is not None:
                pending.append(node.right)
            if node.left is not None:
                pending.append(node.left)

    def post_order(self) -> Iterator[TreeNode[K, V]]:
        pending = [(self.root, False)] if self.root else []
        while pending:
            node, visited = pending.pop()
            if visited:
                yield node
                continue
            pending.append((node, True))
            if node.right is not None:
                pending.append((node.right, False))
            if node.left is not None:
                pending.append((node.left, False))

    def level_order(self) -> Iterator[tuple[TreeNode[K, V], int, TreeNode[K, V] | None]]:
        pending = Queue()
        if self.root is not None:
            pending.enqueue((self.root, 1, None))
        while pending.size:
            node, level, parent = pending.dequeue()
            yield node, level, parent
            if node.left is not None:
                pending.enqueue((node.left, level + 1, node))
            if node.right is not None:
                pending.enqueue((node.right, level + 1, node))

    def traverse(self, order='inorder') -> Iterator[TreeNode[K, V]]:
        methods = {'inorder': self.in_order, 'descending': self.reverse_order,
                   'preorder': self.pre_order, 'postorder': self.post_order}
        if order == 'level':
            return (node for node, _, _ in self.level_order())
        if order not in methods:
            raise ValueError('Recorrido inválido')
        return methods[order]()

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

    def trace(self, key: K) -> list[TreeNode[K, V]]:
        result = []
        current = self.root
        while current is not None:
            result.append(current)
            if key == current.key:
                break
            current = current.left if key < current.key else current.right
        return result
