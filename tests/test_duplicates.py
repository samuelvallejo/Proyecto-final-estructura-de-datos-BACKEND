"""Spatial hash grid and duplicate detector compared with brute force."""
import random
import pytest
from app.duplicates import DuplicateDetector
from app.geo import GeoMath
from app.spatial_index import SpatialHashGrid


def report(identity, lat, lng, timestamp=1, score=50, pothole=None):
    return {'id': identity, 'potholeId': pothole or 'p-' + identity, 'timestamp': timestamp, 'hazardScore': score,
            'location': {'lat': lat, 'lng': lng, 'accuracy': 5}}


def brute_pairs(points, radius):
    keys = list(points)
    return {(a, b) for i, a in enumerate(keys) for b in keys[i + 1:] if GeoMath.distance(points[a], points[b]) <= radius}


@pytest.mark.parametrize('center', [(1.21, -77.29), (4.61, -74.08), (-33.45, -70.66), (64.1, -21.9), (88.5, 10.0)])
def test_close_pairs_match_brute_force(center):
    rng = random.Random(hash(center) & 0xffff)
    grid = SpatialHashGrid[str](20)
    for index in range(400):
        grid.insert(f'k{index}', center[0] + rng.uniform(-0.003, 0.003), center[1] + rng.uniform(-0.003, 0.003))
    pairs, checks = grid.close_pairs(20)
    assert {(a, b) for a, b, _ in pairs} == brute_pairs(grid.points, 20)
    assert checks < 400 * 399 // 2  # The grid inspects far fewer pairs than brute force.


def test_within_returns_sorted_exact_hits():
    grid = SpatialHashGrid[str](10)
    grid.insert('origin', 1.2, -77.29)
    grid.insert('near', 1.20005, -77.29)
    grid.insert('far', 1.2005, -77.29)
    hits = grid.within(1.2, -77.29, 10)
    assert [key for key, _ in hits] == ['origin', 'near'] and hits[1][1] == pytest.approx(5.56, abs=0.05)


def test_invalid_points_are_skipped_and_cells_validated():
    grid = SpatialHashGrid[str](10)
    assert not grid.insert('pole', 89.5, 0) and not grid.insert('nan', float('nan'), 0) and len(grid) == 0
    with pytest.raises(ValueError):
        SpatialHashGrid(0)
    grid.insert('a', 1, 1)
    with pytest.raises(KeyError):
        grid.insert('a', 1, 1)


def test_detector_groups_the_production_pattern():
    # Mirrors production: four reports with identical GPS and three within a metre, plus isolated ones.
    reports = [report(f'same{index}', 1.2114826, -77.2914189, timestamp=10 + index) for index in range(4)]
    reports += [report('pan1', 1.2300968, -77.2902525, 1), report('pan2', 1.2300968, -77.2902526, 2),
                report('pan3', 1.2300967, -77.2902531, 3), report('alone', 1.2296106, -77.2903243, 4)]
    detector = DuplicateDetector(reports, 15)
    clusters = detector.clusters()
    assert [(cluster.canonical['id'], [item['id'] for item in cluster.duplicates]) for cluster in clusters] == [
        ('same0', ['same1', 'same2', 'same3']), ('pan1', ['pan2', 'pan3'])]
    stats = detector.stats()
    assert stats['potholes'] == 8 and stats['duplicates'] == 5 and stats['estimatedPhysicalPotholes'] == 3
    assert clusters[0].as_dict()['maxSpanMeters'] == 0


def test_detector_uses_single_linkage_and_one_vertex_per_pothole():
    chain = [report(str(index), 1.2 + index * 0.0001, -77.29, timestamp=index) for index in range(4)]  # ~11 m apart
    detector = DuplicateDetector(chain, 12)
    [cluster] = detector.clusters()
    assert cluster.canonical['id'] == '0' and cluster.max_span_meters > 30
    same_pothole = [report('a', 1.2, -77.29, 1, pothole='P'), report('b', 1.2, -77.29, 2, pothole='P')]
    assert DuplicateDetector(same_pothole, 10).clusters() == []


def test_detector_validates_radius():
    with pytest.raises(ValueError):
        DuplicateDetector([], 0.5)
    with pytest.raises(ValueError):
        DuplicateDetector([], 51)


def test_both_neighbour_strategies_find_the_same_clusters():
    rng = random.Random(9)
    reports = [report(f'r{index}', 1.21 + rng.uniform(0, 0.002), -77.29 + rng.uniform(0, 0.002), timestamp=index)
               for index in range(150)]
    grid, brute = DuplicateDetector(reports, 10, 'grid'), DuplicateDetector(reports, 10, 'brute-force')
    as_ids = lambda detector: [(c.canonical['id'], [d['id'] for d in c.duplicates]) for c in detector.clusters()]
    assert as_ids(grid) == as_ids(brute)
    assert brute.stats()['candidateChecks'] == brute.stats()['bruteForceChecks'] == 150 * 149 // 2
    assert grid.stats()['candidateChecks'] < brute.stats()['candidateChecks']
    assert (grid.stats()['method'], brute.stats()['method']) == ('grid', 'brute-force')
    with pytest.raises(ValueError):
        DuplicateDetector(reports, 10, 'quadtree')
