"""Indexed max-heap: invariants, index map and comparison against a sorted reference."""
import random
import pytest
from app.priority_queue import IndexedMaxHeap


def reference(items):
    # Expected order: higher priority first, ties by smaller key.
    return sorted(items.items(), key=lambda pair: (-pair[1], pair[0]))


def test_empty_heap_behaviour():
    heap = IndexedMaxHeap()
    assert len(heap) == 0 and not heap and heap.height == -1 and heap.top(3) == []
    assert heap.validate() and not heap.remove('missing')
    with pytest.raises(IndexError):
        heap.pop()
    with pytest.raises(IndexError):
        heap.peek()


def test_heapify_orders_like_sorted_reference():
    rng = random.Random(7)
    items = {f'r{index:03}': rng.randint(0, 100) for index in range(300)}
    heap = IndexedMaxHeap(items.items())
    assert heap.validate() and len(heap) == 300 and heap.height == 8
    assert list(heap.drain()) == reference(items)
    assert len(heap) == 0 and heap.validate()


def test_heapify_is_linear_in_comparisons():
    # Floyd's construction needs fewer than 2n comparisons; n log n would be ~13n here.
    items = [(f'k{index}', index) for index in range(10_000)]
    heap = IndexedMaxHeap(items)
    assert heap.comparisons < 2 * len(items)


def test_ties_are_broken_by_key():
    heap = IndexedMaxHeap([('b', 5), ('a', 5), ('c', 5), ('z', 9)])
    assert [key for key, _ in heap.drain()] == ['z', 'a', 'b', 'c']


def test_duplicate_keys_are_rejected():
    with pytest.raises(KeyError):
        IndexedMaxHeap([('a', 1), ('a', 2)])
    heap = IndexedMaxHeap([('a', 1)])
    with pytest.raises(KeyError):
        heap.push('a', 3)


def test_update_moves_keys_up_and_down():
    heap = IndexedMaxHeap([('a', 10), ('b', 20), ('c', 30)])
    heap.update('a', 99)
    assert heap.peek() == ('a', 99) and heap.validate()
    heap.update('a', 0)
    assert heap.peek() == ('c', 30) and heap.priority_of('a') == 0 and heap.validate()


def test_remove_arbitrary_keys_keeps_index_map():
    heap = IndexedMaxHeap((str(value), value) for value in range(50))
    for key in ['0', '49', '25', '13', '37']:
        assert heap.remove(key) and key not in heap and heap.validate()
    assert len(heap) == 45 and heap.peek() == ('48', 48)


def test_top_does_not_modify_the_heap():
    items = {f'id{index}': (index * 37) % 101 for index in range(120)}
    heap = IndexedMaxHeap(items.items())
    before = len(heap)
    assert heap.top(15) == reference(items)[:15]
    assert heap.top(500) == reference(items)
    assert len(heap) == before and heap.validate()


def test_tuple_priorities_follow_lexicographic_order():
    heap = IndexedMaxHeap([('old', (80, -100)), ('new', (80, -200)), ('low', (40, -1))])
    assert [key for key, _ in heap.drain()] == ['old', 'new', 'low']


def test_random_operations_match_dictionary_reference():
    rng = random.Random(2026)
    heap, model = IndexedMaxHeap(), {}
    for step in range(3000):
        action = rng.random()
        key = f'k{rng.randint(0, 80)}'
        if action < 0.35 and key not in model:
            model[key] = rng.randint(0, 1000)
            heap.push(key, model[key])
        elif action < 0.6 and key in model:
            model[key] = rng.randint(0, 1000)
            heap.update(key, model[key])
        elif action < 0.8:
            assert heap.remove(key) == (key in model)
            model.pop(key, None)
        elif model:
            expected = reference(model)[0]
            assert heap.pop() == expected
            del model[expected[0]]
        if step % 100 == 0:
            assert heap.validate() and len(heap) == len(model)
    assert list(heap.drain()) == reference(model)
