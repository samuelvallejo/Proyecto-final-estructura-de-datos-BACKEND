"""Union-find: set semantics, compression and a randomized check against a naive model."""
import random
import pytest
from app.disjoint_set import DisjointSet


def test_singletons_and_unions():
    sets = DisjointSet('abcde')
    assert len(sets) == 5 and sets.sets == 5 and not sets.add('a')
    assert sets.union('a', 'b') and sets.union('c', 'd') and not sets.union('b', 'a')
    assert sets.connected('a', 'b') and not sets.connected('a', 'c')
    assert sets.union('b', 'd') and sets.connected('a', 'c') and sets.size_of('d') == 4 and sets.sets == 2
    assert sorted(map(sorted, sets.groups())) == [['a', 'b', 'c', 'd'], ['e']]


def test_unknown_elements_raise():
    with pytest.raises(KeyError):
        DisjointSet().find('missing')


def test_path_compression_flattens_long_chains():
    sets = DisjointSet(range(1000))
    for value in range(999):
        sets.union(value, value + 1)
    root = sets.find(0)
    assert all(sets._parent[value] == root for value in range(1000) if sets.find(value) == root)
    # Union by rank keeps the rank logarithmic even before compression.
    assert max(sets._rank.values()) <= 10 and sets.sets == 1


def test_random_unions_match_naive_labels():
    rng = random.Random(11)
    sets, labels = DisjointSet(range(200)), list(range(200))
    for _ in range(400):
        a, b = rng.randrange(200), rng.randrange(200)
        merged = sets.union(a, b)
        assert merged == (labels[a] != labels[b])
        old, new = labels[b], labels[a]
        labels = [new if label == old else label for label in labels]
        assert sets.sets == len(set(labels))
    for a in range(0, 200, 7):
        for b in range(0, 200, 11):
            assert sets.connected(a, b) == (labels[a] == labels[b])
