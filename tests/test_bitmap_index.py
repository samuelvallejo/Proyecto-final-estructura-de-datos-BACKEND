"""Bitmap index: OR inside a field, AND across fields and popcount facets."""
import random
import pytest
from app.bitmap_index import BitmapIndex


def build(rows):
    index = BitmapIndex()
    for identity, risk, damage in rows:
        index.add(identity, {'risk': risk, 'damage': damage})
    return index


ROWS = [('a', 'HIGH', 'BACHE'), ('b', 'LOW', 'GRIETA'), ('c', 'CRITICAL', 'BACHE'), ('d', 'HIGH', 'GRIETA'), ('e', None, 'BACHE')]


def test_or_within_a_field_and_and_across_fields():
    index = build(ROWS)
    severe = index.any_of('risk', ['HIGH', 'CRITICAL'])
    assert list(index.documents(severe)) == ['a', 'c', 'd']
    assert list(index.documents(severe & index.any_of('damage', ['BACHE']))) == ['a', 'c']
    assert index.any_of('risk', None) == index.all and index.count(index.all) == 5
    assert index.any_of('risk', ['UNKNOWN']) == 0 and index.any_of('missing', ['x']) == 0


def test_facet_counts_and_document_sets():
    index = build(ROWS)
    assert index.counts('risk', index.all) == {'CRITICAL': 1, 'HIGH': 2, 'LOW': 1}
    subset = index.of(['a', 'b', 'zzz'])
    assert index.counts('damage', subset) == {'BACHE': 1, 'GRIETA': 1}
    with pytest.raises(KeyError):
        index.add('a', {})


def test_random_filters_match_list_comprehension():
    rng = random.Random(4)
    risks, damages = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'], ['BACHE', 'GRIETA', 'HUNDIMIENTO']
    rows = [(f'r{i}', rng.choice(risks), rng.choice(damages)) for i in range(500)]
    index = build(rows)
    for _ in range(50):
        wanted_risk, wanted_damage = rng.sample(risks, rng.randint(1, 3)), rng.sample(damages, rng.randint(1, 2))
        bits = index.any_of('risk', wanted_risk) & index.any_of('damage', wanted_damage)
        expected = [i for i, r, d in rows if r in wanted_risk and d in wanted_damage]
        assert list(index.documents(bits)) == expected and index.count(bits) == len(expected)
