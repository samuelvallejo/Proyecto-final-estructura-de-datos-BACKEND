"""AVL tree: balance after every operation, ranges and counts against a sorted reference."""
import bisect
import math
import random
from app.avl_tree import AvlTree


def test_sorted_insertions_stay_logarithmic():
    # A plain BST degenerates into a list of height n-1 with sorted keys.
    tree = AvlTree((value, str(value)) for value in range(1024))
    assert len(tree) == 1024 and tree.validate()
    assert tree.height <= 1.44 * math.log2(1024 + 2)
    assert tree.rotations > 0 and [key for key, _ in tree] == list(range(1024))


def test_find_replace_and_remove():
    tree = AvlTree([(5, 'a'), (3, 'b'), (8, 'c')])
    tree.insert(3, 'B')
    assert tree.find(3) == 'B' and len(tree) == 3 and 8 in tree and 9 not in tree
    assert tree.remove(5) and not tree.remove(5)
    assert [key for key, _ in tree] == [3, 8] and tree.validate()
    assert AvlTree().height == -1 and AvlTree().find(1) is None


def test_range_and_counts_with_tuple_keys():
    tree = AvlTree(((day * 1000, f'r{day}'), day) for day in range(50))
    hits = [value for _, value in tree.range((10_000, ''), (14_000, '￿'))]
    assert hits == [10, 11, 12, 13, 14]
    assert tree.count_range((10_000, ''), (14_000, '￿')) == 5
    assert tree.count_range((99_000, ''), (1, '')) == 0
    assert tree.rank((0, '')) == 0 and tree.rank((49_000, 'z')) == 50


def test_random_operations_match_sorted_list():
    rng = random.Random(21)
    tree, model = AvlTree(), []
    for step in range(4000):
        key = rng.randint(0, 600)
        if rng.random() < 0.6:
            tree.insert(key, -key)
            if key not in model:
                bisect.insort(model, key)
        else:
            assert tree.remove(key) == (key in model)
            if key in model:
                model.remove(key)
        if step % 200 == 0:
            assert tree.validate() and [k for k, _ in tree] == model
            low, high = sorted(rng.sample(range(601), 2))
            expected = model[bisect.bisect_left(model, low):bisect.bisect_right(model, high)]
            assert [k for k, _ in tree.range(low, high)] == expected
            assert tree.count_range(low, high) == len(expected)
    assert tree.height <= 1.44 * math.log2(len(model) + 2)
