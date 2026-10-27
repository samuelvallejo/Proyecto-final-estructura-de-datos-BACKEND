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


def test_empty_traversals():
    tree = BinarySearchTree()
    assert all(list(tree.traverse(order)) == [] for order in ['inorder', 'descending', 'preorder', 'postorder', 'level'])


def test_pdf_inorder_example():
    assert keys(example().in_order()) == [1, 2, 3, 5, 6, 7, 8]


def test_reverse_order():
    assert keys(example().reverse_order()) == [8, 7, 6, 5, 3, 2, 1]


def test_preorder():
    assert keys(example().pre_order()) == [5, 2, 1, 3, 7, 6, 8]


def test_postorder():
    assert keys(example().post_order()) == [1, 3, 2, 6, 8, 7, 5]


def test_root_level_and_parent():
    root, level, parent = next(example().level_order())
    assert root.key == 5 and level == 1 and parent is None


def test_level_order_fifo():
    assert [(node.key, level) for node, level, _ in example().level_order()] == [(5,1),(2,2),(7,2),(1,3),(3,3),(6,3),(8,3)]


def test_empty_height():
    assert BinarySearchTree().height == -1 and BinarySearchTree().metrics()['levels'] == 0
