"""Maintenance rules: status workflow graph, explainable priority and day route."""
import itertools
import random
import pytest
from app.maintenance import DAY_MS, MaintenancePriority, MaintenanceQueue, RoutePlanner, StatusWorkflow

NOW = 1_800_000_000_000


def report(identity, score=50, people=0, passes=0, age_days=0, status='UNVERIFIED', lat=1.2, lng=-77.29):
    return {'id': identity, 'hazardScore': score, 'peopleCount': people, 'passCount': passes,
            'timestamp': NOW - int(age_days * DAY_MS), 'status': status,
            'location': {'lat': lat, 'lng': lng, 'accuracy': 5}}


class TestStatusWorkflow:
    def test_allowed_transitions(self):
        flow = StatusWorkflow()
        assert flow.allowed('UNVERIFIED') == ['CONFIRMED', 'REJECTED']
        assert flow.can_move('CONFIRMED', 'IN_PROGRESS') and not flow.can_move('UNVERIFIED', 'REPAIRED')
        assert flow.is_terminal('REPAIRED') and flow.is_terminal('REJECTED') and not flow.is_terminal('CONFIRMED')
        assert flow.allowed('UNKNOWN') == []

    def test_shortest_path_uses_bfs(self):
        flow = StatusWorkflow()
        assert flow.shortest_path('UNVERIFIED', 'REPAIRED') == ['UNVERIFIED', 'CONFIRMED', 'IN_PROGRESS', 'REPAIRED']
        assert flow.shortest_path('IN_PROGRESS', 'IN_PROGRESS') == ['IN_PROGRESS']
        assert flow.shortest_path('REPAIRED', 'CONFIRMED') == []

    def test_unknown_targets_are_rejected(self):
        with pytest.raises(ValueError):
            StatusWorkflow({'A': ('B',)})


class TestMaintenancePriority:
    def test_components_add_up_and_are_bounded(self):
        breakdown = MaintenancePriority().evaluate(report('a', 100, people=500, passes=5000, age_days=400, status='CONFIRMED'), NOW)
        assert breakdown.score == 100 and breakdown.hazard == 55 and breakdown.waiting == 10
        low = MaintenancePriority().evaluate(report('b', 0), NOW)
        assert low.score == 0
        parts = breakdown.as_dict()['components']
        assert round(sum(parts.values()), 2) == breakdown.score

    def test_exposure_and_aging_raise_priority(self):
        policy = MaintenancePriority()
        base = policy.evaluate(report('a', 60), NOW).score
        assert policy.evaluate(report('a', 60, people=5), NOW).score > base
        assert policy.evaluate(report('a', 60, age_days=8), NOW).score == base + 4

    def test_future_timestamps_do_not_add_waiting(self):
        assert MaintenancePriority().evaluate(report('a', 60, age_days=-3), NOW).waiting == 0


class TestMaintenanceQueue:
    def test_top_matches_full_sort(self):
        rng = random.Random(3)
        reports = [report(f'r{index}', rng.randint(0, 100), rng.randint(0, 9), rng.randint(0, 30), rng.random() * 30)
                   for index in range(200)]
        queue = MaintenanceQueue(reports, NOW)
        policy = MaintenancePriority()
        expected = sorted(reports, key=lambda item: (-policy.evaluate(item, NOW).score, item['timestamp'], item['id']))
        assert [item['id'] for item, _ in queue.top(25)] == [item['id'] for item in expected[:25]]
        assert len(queue) == 200

    def test_older_report_wins_a_score_tie(self):
        # Same score; the report waiting longer goes first even though the id sorts later.
        queue = MaintenanceQueue([report('a-new', 70, age_days=0), report('z-old', 70, age_days=0.001)], NOW)
        policy = MaintenancePriority()
        assert policy.evaluate(queue.reports['a-new'], NOW).score == policy.evaluate(queue.reports['z-old'], NOW).score
        assert [item['id'] for item, _ in queue.top(2)] == ['z-old', 'a-new']


def brute_force_length(planner, fixed_start):
    nodes = list(range(1 if fixed_start else 0, len(planner.matrix)))
    best = float('inf')
    for permutation in itertools.permutations(nodes):
        path = ([0] if fixed_start else []) + list(permutation)
        best = min(best, planner.length(path))
    return best


class TestRoutePlanner:
    def grid(self, count, seed):
        rng = random.Random(seed)
        return [report(f's{index}', lat=1.20 + rng.random() * 0.03, lng=-77.30 + rng.random() * 0.03)
                for index in range(count)]

    def test_plan_is_a_permutation_and_never_worse_than_priority_order(self):
        for seed in range(15):
            stops = self.grid(9, seed)
            plan = RoutePlanner({'lat': 1.21, 'lng': -77.29}, stops).plan()
            assert sorted(plan['order']) == list(range(9))
            assert plan['totalMeters'] <= plan['priorityOrderMeters'] + 0.1
            assert 0 <= plan['savedPercent'] <= 100
            assert len(plan['legsMeters']) == 9 and all(leg is not None for leg in plan['legsMeters'])
            assert abs(sum(plan['legsMeters']) - plan['totalMeters']) < 1  # legs are rounded to 0.1 m

    def test_heuristic_is_close_to_the_optimum_on_small_inputs(self):
        for seed in range(10):
            planner = RoutePlanner({'lat': 1.21, 'lng': -77.29}, self.grid(7, seed))
            plan = planner.plan()
            assert plan['totalMeters'] <= brute_force_length(planner, True) * 1.10 + 0.5

    def test_without_start_point_first_stop_has_no_leg(self):
        plan = RoutePlanner(None, self.grid(6, 1)).plan()
        assert plan['legsMeters'][0] is None and sorted(plan['order']) == list(range(6))

    def test_two_opt_untangles_a_crossing(self):
        # Priority order zig-zags across a straight street; the plan must walk it in order.
        stops = [report(str(index), lat=1.2, lng=-77.29 + offset) for index, offset in
                 enumerate([0.000, 0.004, 0.001, 0.003, 0.002])]
        plan = RoutePlanner({'lat': 1.2, 'lng': -77.2905}, stops).plan()
        assert plan['order'] == [0, 2, 4, 3, 1]
        assert plan['savedPercent'] > 50

    def test_empty_and_single_stop(self):
        assert RoutePlanner(None, []).plan()['order'] == []
        single = RoutePlanner({'lat': 1.2, 'lng': -77.29}, [report('a', lat=1.201, lng=-77.29)]).plan()
        assert single['order'] == [0] and single['totalMeters'] > 100
