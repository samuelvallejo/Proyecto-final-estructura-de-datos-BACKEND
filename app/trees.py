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
