import math
import random
import pytest
from app.graphs import WeightedGraph
from app.report_graphs import ReportProximityGraph
from app.repository import distance
from tree_helpers import report


def graph(vertices, edges):
    result = WeightedGraph()
    for vertex in vertices:
        result.add_vertex(vertex)
    for source, target, weight in edges:
        result.add_edge(source, target, weight)
    return result


def test_undirected_edges_update_and_removal_preserve_neighbors():
    g = graph('abc', [('a', 'b', 4), ('b', 'c', 2)])
    g.add_edge('b', 'a', 7)
    assert g.adjacency['a']['b'] == g.adjacency['b']['a'] == 7
    assert len(g.edges()) == 2
    g.remove_vertex('b')
    assert g.adjacency == {'a': {}, 'c': {}}
    g.remove_vertex('missing'); g.remove_edge('a', 'c')


@pytest.mark.parametrize('weight', [-1, float('inf'), float('nan'), True, '3'])
def test_invalid_weights_rejected_without_mutation(weight):
    g = graph('ab', [])
    with pytest.raises(ValueError):
        g.add_edge('a', 'b', weight)
    assert g.adjacency == {'a': {}, 'b': {}}


def test_invalid_vertices_edges_and_orders():
    g = graph('ab', [])
    for edge in [('a', 'a', 1), ('a', 'missing', 1)]:
        with pytest.raises(ValueError): g.add_edge(*edge)
    with pytest.raises(ValueError): g.add_vertex('')
    with pytest.raises(ValueError): g.traverse('a', 'random')
    with pytest.raises(ValueError): g.shortest_path('a', 'missing')


def test_bfs_and_dfs_visit_cycles_once_and_exclude_unreachable_nodes():
    g = graph('abcdef', [('a', 'b', 1), ('a', 'c', 1), ('b', 'd', 1), ('d', 'c', 1), ('c', 'e', 1)])
    assert g.traverse('a', 'bfs') == ['a', 'b', 'c', 'd', 'e']
    assert g.traverse('a', 'dfs') == ['a', 'b', 'd', 'c', 'e']
    assert g.components() == [['a', 'b', 'c', 'd', 'e'], ['f']]
    g.remove_edge('a', 'b')
    assert 'b' not in g.adjacency['a'] and 'a' not in g.adjacency['b']


def test_dijkstra_chooses_weight_over_number_of_edges():
    g = graph('abcdz', [('a', 'd', 20), ('a', 'b', 3), ('b', 'c', 2), ('c', 'd', 1)])
    path = g.shortest_path('a', 'd')
    assert path['reportIds'] == ['a', 'b', 'c', 'd'] and path['distanceMeters'] == 6
    assert path['reachable'] and path['settledIds'] == ['a', 'b', 'c', 'd']
    assert g.shortest_path('a', 'z')['distanceMeters'] is None
    assert g.shortest_path('a', 'a')['reportIds'] == ['a']
    assert g.shortest_path('a', 'a')['distanceMeters'] == 0


def test_dijkstra_zero_weight_cycles_and_stale_heap_entries():
    g = graph('abcd', [('a', 'b', 10), ('a', 'c', 1), ('c', 'b', 0), ('b', 'd', 20)])
    assert g.shortest_path('a', 'd')['distanceMeters'] == 21
    assert len(g.shortest_path('a', 'd')['settledIds']) == 4


def test_dijkstra_matches_floyd_warshall_oracle():
    rng = random.Random(81)
    vertices = list('abcdefgh')
    edges = [(a, b, rng.randrange(0, 25)) for i, a in enumerate(vertices) for b in vertices[i + 1:] if rng.random() < .4]
    g = graph(vertices, edges)
    costs = {(a, b): 0 if a == b else math.inf for a in vertices for b in vertices}
    for a, b, weight in edges: costs[a, b] = costs[b, a] = weight
    for k in vertices:
        for a in vertices:
            for b in vertices: costs[a, b] = min(costs[a, b], costs[a, k] + costs[k, b])
    for a in vertices:
        for b in vertices:
            path = g.shortest_path(a, b)
            assert path['reachable'] == math.isfinite(costs[a, b])
            assert path['distanceMeters'] == (costs[a, b] if math.isfinite(costs[a, b]) else None)


def positioned(identity, lat, lng=-76.53):
    result = report(identity)
    result['location']['lat'], result['location']['lng'] = lat, lng
    return result


def test_report_network_uses_real_distance_chain_and_isolated_components():
    reports = [positioned('a', 3.45), positioned('b', 3.451), positioned('c', 3.452), positioned('d', 4)]
    network = ReportProximityGraph(reports, 150)
    snapshot = network.snapshot('a', 'c', 'dfs')
    assert snapshot['metrics'] == {'vertices': 4, 'edges': 2, 'components': 2, 'isolated': 1, 'maxDegree': 2}
    assert snapshot['traversal']['reportIds'] == ['a', 'b', 'c']
    assert snapshot['path']['reportIds'] == ['a', 'b', 'c']
    assert snapshot['path']['distanceMeters'] == pytest.approx(distance(reports[0]['location'], reports[1]['location']) * 2)
    assert len(ReportProximityGraph(reports, 250).snapshot()['edges']) == 3


def test_coincident_antimeridian_and_invalid_coordinates():
    network = ReportProximityGraph([positioned('a', 0, 179.9999), positioned('b', 0, -179.9999),
                                    positioned('c', 0, 179.9999), positioned('bad', float('nan'))], 50)
    assert len(network.reports) == 3 and len(network.graph.edges()) == 3
    assert network.graph.shortest_path('a', 'c')['distanceMeters'] == 0


def test_empty_network_and_missing_selection():
    empty = ReportProximityGraph([], 250).snapshot()
    assert empty['metrics']['components'] == 0 and empty['traversal']['reportIds'] == [] and empty['path'] is None
    with pytest.raises(ValueError): ReportProximityGraph([], 49)
    with pytest.raises(ValueError): ReportProximityGraph([report('a')], 250).snapshot('unknown')
