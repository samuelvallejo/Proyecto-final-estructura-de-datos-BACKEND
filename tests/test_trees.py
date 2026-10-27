import random
import pytest
from app.trees import BinarySearchTree, TreeNode
from app.report_trees import ReportRiskIndex, ReportPlaceTree, report_key, place_key, place_id
from tree_helpers import report

def example():
    tree = BinarySearchTree()
    for value in [5, 2, 7, 1, 3, 6, 8]:
        tree.insert(value, str(value))
    return tree

def keys(nodes):
    return [node.key for node in nodes]


def test_empty_root_and_weight():
    tree = BinarySearchTree()
    assert tree.root is None and len(tree) == 0 and not tree


def test_first_insert_is_root():
    tree = BinarySearchTree(); assert tree.insert(5, 'raíz')
    assert tree.root.key == 5 and tree.root.value == 'raíz' and len(tree) == 1
