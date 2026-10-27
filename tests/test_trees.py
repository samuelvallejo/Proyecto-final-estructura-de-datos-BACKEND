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


def test_single_height():
    tree = BinarySearchTree(); tree.insert(1, 1)
    assert tree.height == 0 and tree.metrics()['levels'] == 1


def test_skewed_tree_without_recursion():
    tree = BinarySearchTree()
    for value in range(1300): tree.insert(value, value)
    assert tree.height == 1299 and len(list(tree.post_order())) == 1300 and tree.validate()


def test_complete_metrics():
    assert example().metrics() == {'weight':7,'height':2,'levels':3,'leaves':4,'branches':2,'internalNodes':3,'order':2,'maxDegree':2}


def test_root_not_a_branch():
    tree = BinarySearchTree(); tree.insert(2,2); tree.insert(1,1)
    assert tree.metrics()['branches'] == 0 and tree.metrics()['leaves'] == 1


def test_range_inclusive():
    assert keys(example().between(2,7)) == [2,3,5,6,7]


def test_range_outside():
    assert list(example().between(20,30)) == []


def test_range_reversed():
    with pytest.raises(ValueError): list(example().between(7,2))


def test_remove_absent():
    tree = example(); assert not tree.remove(99) and len(tree) == 7


def test_remove_left_leaf():
    tree = example(); assert tree.remove(1) and tree.root.left.left is None and tree.validate()


def test_remove_right_leaf():
    tree = example(); assert tree.remove(8) and tree.root.right.right is None and tree.validate()


def test_remove_single_root():
    tree = BinarySearchTree(); tree.insert(1,1); assert tree.remove(1)
    assert tree.root is None and len(tree) == 0 and tree.validate()


def test_remove_root_with_left():
    tree = BinarySearchTree(); tree.insert(2,2); tree.insert(1,1); tree.remove(2)
    assert tree.root.key == 1 and tree.validate()


def test_remove_root_with_right():
    tree = BinarySearchTree(); tree.insert(1,1); tree.insert(2,2); tree.remove(1)
    assert tree.root.key == 2 and tree.validate()


def test_remove_internal_left_child():
    tree = example(); tree.remove(3); tree.remove(2)
    assert tree.root.left.key == 1 and tree.validate()


def test_remove_internal_right_child():
    tree = example(); tree.remove(6); tree.remove(7)
    assert tree.root.right.key == 8 and tree.validate()


def test_remove_two_children_immediate_successor():
    tree = BinarySearchTree.from_items([(1,'a'),(2,'b'),(3,'c')]); tree.remove(2)
    assert keys(tree.in_order()) == [1,3] and tree.validate()


def test_remove_deep_successor_preserves_its_child():
    tree = BinarySearchTree()
    for value in [10,5,20,15,17,25]: tree.insert(value,str(value))
    tree.remove(10)
    assert keys(tree.in_order()) == [5,15,17,20,25] and tree.search(17) == '17' and tree.validate()


def test_balanced_bulk_build():
    tree = BinarySearchTree.from_items((n,n) for n in range(200))
    assert tree.height == 7 and tree.validate() and len(tree) == 200


def test_bulk_duplicates_last_value():
    tree = BinarySearchTree.from_items([(2,'a'),(1,'b'),(2,'c')])
    assert len(tree) == 2 and tree.search(2) == 'c'


def test_rebalance_preserves_values():
    tree = BinarySearchTree()
    for n in range(30): tree.insert(n,str(n))
    before = [(node.key,node.value) for node in tree.in_order()]; tree.rebalance()
    assert tree.height == 4 and [(node.key,node.value) for node in tree.in_order()] == before


def test_validate_corrupt_order():
    tree = example(); tree.root.left.right.key = 99
    assert not tree.validate()


def test_validate_cycle():
    tree = example(); tree.root.left.left = tree.root
    assert not tree.validate()


def test_validate_weight_mismatch():
    tree = example(); tree.size += 1
    assert not tree.validate()


def test_clear_and_reuse():
    tree = example(); tree.clear(); tree.insert(9,'nueve')
    assert len(tree) == 1 and tree.search(9) == 'nueve' and tree.validate()


def test_composite_keys():
    tree = BinarySearchTree(); tree.insert((70,1,'a'),'a'); tree.insert((70,1,'b'),'b')
    assert len(tree) == 2 and [node.value for node in tree.in_order()] == ['a','b']


def test_random_mutations_preserve_bst():
    rng = random.Random(315); tree = BinarySearchTree(); expected = {}
    for _ in range(500):
        key = rng.randrange(100)
        if rng.random() < .6: expected[key] = key*2; tree.insert(key,key*2)
        else: expected.pop(key,None); tree.remove(key)
        assert tree.validate() and [(n.key,n.value) for n in tree.in_order()] == sorted(expected.items())


def test_unknown_traversal():
    with pytest.raises(ValueError): example().traverse('invalid')


def test_queries_are_non_mutating():
    tree = example(); before = keys(tree.pre_order())
    list(tree.between(2,7)); tree.search(3); tree.trace(9); tree.metrics()
    assert keys(tree.pre_order()) == before and tree.validate()


def test_report_index_duplicate_identity():
    index = ReportRiskIndex([report('a',20),report('a',80)])
    assert index.tree.size == 1 and index.ordered()[0]['hazardScore'] == 80


def test_report_index_equal_scores():
    index = ReportRiskIndex([report('a'),report('b')])
    assert {r['id'] for r in index.ordered()} == {'a','b'}


def test_report_key_tie_order():
    index = ReportRiskIndex([report('b'),report('a')])
    assert [r['id'] for r in index.ordered('inorder')] == ['a','b']


def test_report_risk_order():
    index = ReportRiskIndex([report('a',20),report('b',90),report('c',60)])
    assert [r['hazardScore'] for r in index.ordered()] == [90,60,20]


def test_report_upsert_moves_key():
    index = ReportRiskIndex([report('a',20),report('b',60)]); index.upsert(report('a',90))
    assert [r['id'] for r in index.ordered()] == ['a','b'] and index.tree.size == 2


def test_invalid_upsert_preserves_previous():
    index = ReportRiskIndex([report('a',20)])
    with pytest.raises(ValueError): index.upsert(report('a',101))
    assert index.ordered()[0]['hazardScore'] == 20


def test_report_remove_identity():
    index = ReportRiskIndex([report('a')]); assert index.remove('a') and not index.remove('a') and index.tree.size == 0


def test_report_range_zero_and_hundred():
    index = ReportRiskIndex([report('a',0),report('b',100),report('c',50)])
    assert [r['id'] for r in index.in_range(0,0)] == ['a']
    assert [r['id'] for r in index.in_range(100,100)] == ['b']


def test_report_search_path():
    index = ReportRiskIndex(report(str(n),n) for n in range(7)); path = index.search_path('1')
    assert path[0] == index.tree.root.value['id'] and path[-1] == '1' and index.search_path('missing') == []


def test_binary_snapshot_links():
    snapshot = ReportRiskIndex(report(str(n),n) for n in range(7)).snapshot()
    nodes = {node['id']:node for node in snapshot['nodes']}
    for node in nodes.values():
        for child in [node['leftId'],node['rightId']]:
            if child is not None: assert nodes[child]['parentId'] == node['id'] and nodes[child]['level'] == node['level']+1


def test_binary_snapshot_excludes_private_fields():
    value = report(); value['session_id'] = 'secret'; value['email'] = 'private@example.invalid'
    snapshot = str(ReportRiskIndex([value]).snapshot())
    assert 'secret' not in snapshot and 'private@example.invalid' not in snapshot and 'session_id' not in snapshot


def test_invalid_scores():
    for value in [True, float('nan'), float('inf'), -1, 101]:
        with pytest.raises(ValueError): report_key(report(score=value))


def test_invalid_timestamps():
    for value in [-1, float('inf'), True]:
        with pytest.raises(ValueError): report_key(report(timestamp=value))


def test_invalid_report_ids():
    for value in ['',None,12]:
        with pytest.raises(ValueError): report_key(report(identity=value))


def test_invalid_report_range():
    with pytest.raises(ValueError): ReportRiskIndex().in_range(90,10)


def test_empty_report_snapshot():
    value = ReportRiskIndex().snapshot()
    assert value['rootId'] is None and value['nodes'] == [] and value['traversal']['reportIds'] == []


def test_places_unknown_labels():
    tree = ReportPlaceTree([report(city=None,neighborhood=None,street=None)])
    assert {'Ciudad sin identificar','Barrio sin identificar','Vía sin identificar'} <= {node.label for node in tree.nodes.values()}


def test_places_normalization():
    tree = ReportPlaceTree([report('a',city=' Bogotá '),report('b',city='BOGOTA')])
    assert len(tree.root.children) == 1 and tree.root.children[0].report_count == 2


def test_neighborhoods_keep_city_scope():
    tree = ReportPlaceTree([report('a',city='Cali'),report('b',city='Bogotá')])
    assert len([node for node in tree.nodes.values() if node.kind == 'neighborhood']) == 2


def test_streets_keep_neighborhood_scope():
    tree = ReportPlaceTree([report('a',neighborhood='Centro'),report('b',neighborhood='Norte')])
    assert len([node for node in tree.nodes.values() if node.kind == 'street']) == 2
