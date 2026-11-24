"""Route strategies and factory: interchangeable algorithms with comparable results."""
import random
import pytest
from app.route_planning import (NearestNeighbourConstruction, NoImprovement, PriorityOrderConstruction, RouteImprovement,
                                RoutePlanner, RoutePlannerFactory, TwoOptImprovement)


def stops(count, seed):
    rng = random.Random(seed)
    return [{'id': f's{index}', 'location': {'lat': 1.20 + rng.random() * 0.03, 'lng': -77.30 + rng.random() * 0.03}}
            for index in range(count)]


START = {'lat': 1.21, 'lng': -77.29}


def test_factory_builds_each_algorithm_with_its_strategies():
    assert RoutePlannerFactory.names() == ['two-opt', 'nearest-neighbour', 'priority']
    planner = RoutePlannerFactory.create('nearest-neighbour', START, stops(4, 1))
    assert isinstance(planner.construction, NearestNeighbourConstruction) and isinstance(planner.improvement, NoImprovement)
    planner = RoutePlannerFactory.create('priority', START, stops(4, 1))
    assert isinstance(planner.construction, PriorityOrderConstruction)
    with pytest.raises(ValueError):
        RoutePlannerFactory.create('genetic', START, [])


def test_better_strategies_never_lengthen_the_route():
    for seed in range(20):
        data = stops(10, seed)
        totals = {name: RoutePlannerFactory.create(name, START, data).plan() for name in RoutePlannerFactory.names()}
        assert totals['priority']['savedPercent'] == 0 and totals['priority']['order'] == list(range(10))
        assert totals['two-opt']['totalMeters'] <= totals['nearest-neighbour']['totalMeters'] + 0.1
        assert totals['nearest-neighbour']['totalMeters'] <= totals['priority']['totalMeters'] + 0.1
        assert all(plan['algorithm'] == name for name, plan in totals.items())


def test_two_opt_is_a_pure_improvement_step():
    matrix = [[0, 1, 4, 2], [1, 0, 2, 4], [4, 2, 0, 1], [2, 4, 1, 0]]
    path, changes = TwoOptImprovement().improve(matrix, [0, 2, 1, 3], fixed_start=True)
    assert path[0] == 0 and changes >= 1 and sum(matrix[a][b] for a, b in zip(path, path[1:])) == 4


def test_a_new_strategy_plugs_in_without_changing_the_planner():
    class ReverseImprovement(RouteImprovement):
        def improve(self, matrix, path, fixed_start):
            return path[:1] + path[1:][::-1], 1
    plan = RoutePlanner(START, stops(5, 3), PriorityOrderConstruction(), ReverseImprovement(), 'reverse').plan()
    assert plan['algorithm'] == 'reverse' and sorted(plan['order']) == list(range(5))
