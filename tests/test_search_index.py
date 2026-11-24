"""Tokenizer, prefix trie, inverted index and report ranking."""
import random
from app.search_index import InvertedIndex, PrefixTrie, ReportSearchIndex, Tokenizer


def report(identity, street=None, neighborhood=None, city='Pasto', score=50, timestamp=1, level='MEDIUM',
           kind='BACHE', status='UNVERIFIED', text=''):
    return {'id': identity, 'hazardScore': score, 'hazardLevel': level, 'potholeType': kind, 'status': status,
            'timestamp': timestamp, 'aiDescription': text,
            'zone': {'street': street, 'neighborhood': neighborhood, 'city': city, 'fullAddress': None}}


REPORTS = [
    report('a', 'Avenida Panamericana', 'La Primavera', score=35, timestamp=5),
    report('b', 'Avenida Panamericana', 'La Primavera', score=80, level='CRITICAL', timestamp=3),
    report('c', 'Carrera 45', 'Pandiaco', score=70, level='HIGH', text='Hueco profundo junto al andén'),
    report('d', 'Calle 18', 'Universitario', score=70, level='HIGH', timestamp=9),
    report('e', 'Calle Panamá', 'Centro', city='Bogotá', score=20, level='LOW', status='CONFIRMED'),
]


def test_tokenizer_removes_accents_case_and_stop_words():
    tokens = Tokenizer().tokens('Hundimiento en la AVENIDA Panamericana, Bogotá D.C.')
    assert tokens == ['hundimiento', 'avenida', 'panamericana', 'bogota']
    assert Tokenizer().tokens('de la y') == []


def test_trie_completes_by_weight_then_alphabetically():
    trie = PrefixTrie()
    for word, weight in [('pandiaco', 3), ('panamericana', 5), ('panama', 3), ('pasto', 9)]:
        trie.insert(word, word, weight)
    assert trie.complete('pan', 10) == [('panamericana', 5), ('panama', 3), ('pandiaco', 3)]
    assert trie.complete('pan', 1) == [('panamericana', 5)]
    assert trie.complete('x', 5) == [] and trie.collect('') == {'pandiaco': 3, 'panamericana': 5, 'panama': 3, 'pasto': 9}
    trie.insert('pasto', 'pasto')
    assert trie.collect('pas') == {'pasto': 10}


def test_inverted_index_intersects_smallest_first():
    index = InvertedIndex()
    index.add('1', {'calle', 'pasto'})
    index.add('2', {'calle', 'cali'})
    index.add('3', {'carrera', 'pasto'})
    assert index.intersect([index.documents('calle'), index.documents('pasto')]) == {'1'}
    assert index.intersect([index.documents('missing'), index.documents('calle')]) == set()
    assert index.intersect([]) == set()


def test_search_matches_all_words_and_completes_the_last_one():
    index = ReportSearchIndex(REPORTS)
    results, tokens = index.search('avenida panam')
    assert tokens == ['avenida', 'panam'] and [item['id'] for item in results] == ['b', 'a']
    assert [item['id'] for item in index.search('PANAMÁ')[0]] == ['e']  # Exact word is also a prefix of itself.
    assert [item['id'] for item in index.search('critico')[0]] == ['b']
    assert [item['id'] for item in index.search('hueco profundo')[0]] == ['c']
    assert index.search('la de') == ([], [])
    assert index.search('cartagena')[0] == []


def test_place_matches_rank_above_description_matches():
    reports = [report('place', 'Calle Hueco', score=10), report('text', 'Calle 1', score=99, text='Hueco grande')]
    assert [item['id'] for item in ReportSearchIndex(reports).search('hueco')[0]] == ['place', 'text']


def test_ties_rank_by_risk_then_recency():
    results, _ = ReportSearchIndex(REPORTS).search('pasto')
    assert [item['id'] for item in results] == ['b', 'd', 'c', 'a']


def test_place_suggestions_count_reports_and_match_any_word_start():
    index = ReportSearchIndex(REPORTS)
    assert index.suggest('panam', 5) == [{'label': 'Avenida Panamericana', 'kind': 'street', 'count': 2},
                                         {'label': 'Calle Panamá', 'kind': 'street', 'count': 1}]
    assert index.suggest('prim', 5) == [{'label': 'La Primavera', 'kind': 'neighborhood', 'count': 2}]
    assert index.suggest('p', 5) == []
    stats = index.stats()
    assert stats['documents'] == 5 and stats['terms'] > 10 and stats['trieNodes'] > stats['terms']


def test_search_agrees_with_linear_scan_on_random_data():
    rng = random.Random(5)
    streets = ['Calle 18', 'Carrera 45', 'Avenida Panamericana', 'Calle Panamá', 'Avenida Boyacá', 'Carrera 27']
    places = ['Centro', 'Pandiaco', 'Universitario', 'La Primavera', 'Tamasagra']
    reports = [report(f'r{index}', rng.choice(streets), rng.choice(places), score=rng.randint(0, 100), timestamp=index)
               for index in range(300)]
    index, tokenizer = ReportSearchIndex(reports), Tokenizer()
    for query in ['carrera', 'avenida pana', 'centro calle', 'pandiaco 45', 'boy', 'tamasagra panamericana']:
        words = tokenizer.tokens(query)
        expected = {item['id'] for item in reports if all(
            any(token == word or (position == len(words) - 1 and token.startswith(word))
                for token in tokenizer.tokens(f"{item['zone']['street']} {item['zone']['neighborhood']} {item['zone']['city']} "
                                              f"{'moderado medio'} bache hueco sin verificar"))
            for position, word in enumerate(words))}
        assert {item['id'] for item in index.search(query)[0]} == expected, query


def test_filters_combine_text_categories_and_dates_with_facets():
    index = ReportSearchIndex(REPORTS)
    result = index.filter('pasto', risk=['HIGH', 'CRITICAL'])
    assert [item['id'] for item in result['reports']] == ['b', 'd', 'c']
    # Risk counts ignore the risk filter; damage counts apply it.
    assert result['facets']['risk'] == {'CRITICAL': 1, 'HIGH': 2, 'MEDIUM': 1}
    assert result['facets']['damage'] == {'BACHE': 3}
    dated = index.filter(None, since=3, until=5)
    assert [item['id'] for item in dated['reports']] == ['b', 'a'] and dated['tokens'] == []
    assert index.filter(None, damage=['GRIETA'])['reports'] == []
    assert [item['id'] for item in index.filter('calle', since=9)['reports']] == ['d']
    assert index.stats()['dateTreeHeight'] >= 1


def test_filters_agree_with_a_linear_scan():
    rng = random.Random(8)
    levels = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
    reports = [report(f'r{i}', rng.choice(['Calle 18', 'Carrera 45']), 'Centro', level=rng.choice(levels),
                      timestamp=rng.randint(0, 1000)) for i in range(300)]
    index = ReportSearchIndex(reports)
    for _ in range(40):
        wanted = rng.sample(levels, 2)
        low, high = sorted(rng.sample(range(1001), 2))
        got = {item['id'] for item in index.filter('carrera', risk=wanted, since=low, until=high)['reports']}
        expected = {item['id'] for item in reports if item['zone']['street'] == 'Carrera 45'
                    and item['hazardLevel'] in wanted and low <= item['timestamp'] <= high}
        assert got == expected
