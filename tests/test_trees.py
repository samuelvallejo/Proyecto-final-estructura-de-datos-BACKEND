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


def test_insert_left():
    tree = example(); assert tree.root.left.key == 2 and tree.root.left.left.key == 1


def test_insert_right():
    tree = example(); assert tree.root.right.key == 7 and tree.root.right.right.key == 8


def test_equal_key_updates_value():
    tree = example(); assert not tree.insert(3, 'nuevo')
    assert tree.search(3) == 'nuevo' and len(tree) == 7


def test_search_root():
    assert example().search(5) == '5'


def test_search_left_descendant():
    assert example().search(1) == '1'


def test_search_right_descendant():
    assert example().search(8) == '8'


def test_search_absent():
    tree = example(); assert tree.search(4) is None and not tree.contains(4)


def test_contains_none_value():
    tree = BinarySearchTree(); tree.insert(1, None)
    assert tree.contains(1) and tree.search(1) is None
