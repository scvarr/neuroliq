"""Полные traces M5.2 и контроль неизменной топологии M5.1."""

from copy import deepcopy
from pathlib import Path

import pytest

from neuroliq.activation import Activation
from neuroliq.experiment import ExperimentDefinition
from neuroliq.m5_2 import run_directional, scenario_weights


M5_1 = Path(__file__).resolve().parents[1] / "experiments/m5-1-backwave-echo.neuroliq.json"


def structure(graph):
    return (graph.concepts(), graph.connections(),
            tuple(graph.neighbors(c.id) for c in graph.concepts()))


def setup():
    definition = ExperimentDefinition.load(M5_1)
    graph, labels = definition.build()
    return definition, graph, labels, scenario_weights(graph, labels)


def test_symmetric_control_exactly_reproduces_m5_1_full_snapshot():
    definition, graph, labels, weights = setup()
    before = structure(graph)
    baseline = Activation(graph)
    baseline.start(**definition.run.model_dump())
    baseline.run()
    result = run_directional(graph, weights["symmetric_control"], **definition.run.model_dump())
    comparable = deepcopy(result)
    for trace in comparable["traces"]:
        for transition in trace["transitions"]:
            assert transition.pop("route_weight") == 1.0
    assert comparable == baseline.snapshot()
    assert result["traces"][1]["candidates"] == result["traces"][3]["candidates"] == result["traces"][5]["candidates"]
    assert result["traces"][2]["candidates"] == result["traces"][4]["candidates"] == result["traces"][6]["candidates"]
    assert all(not trace["pruned"] for trace in result["traces"])
    assert structure(graph) == before


def test_asymmetric_full_trace_matches_prediction_without_pruning_or_graph_changes():
    definition, graph, labels, weights = setup()
    before = structure(graph)
    ids = {label: cid for cid, label in labels.items()}
    names = {str(cid): label for cid, label in labels.items()}
    assert len(graph.concepts()) == 7
    assert len(graph.connections()) == 6
    assert all(c.strength == 1.0 for c in graph.connections())
    assert {frozenset((labels[c.concept_a], labels[c.concept_b]))
            for c in graph.connections()} == {frozenset(pair) for pair in ("AC", "CX", "DX", "BD", "CE", "DF")}
    for c in graph.connections():
        assert graph.get_connection(c.concept_a, c.concept_b) is graph.get_connection(c.concept_b, c.concept_a)
    assert definition.run.model_dump() == dict(seeds={ids["A"]: 1.0, ids["B"]: 1.0},
                                             decay=0.5, max_active=7, max_steps=6)
    result = run_directional(graph, weights["asymmetric_traversal"], **definition.run.model_dump())
    expected = [
        [("A", 1.0), ("B", 1.0)], [("C", 0.5), ("D", 0.5)],
        [("X", 0.5), ("E", 0.25), ("F", 0.25), ("A", 0.125), ("B", 0.125)],
        [("C", 0.25), ("D", 0.25)],
        [("X", 0.25), ("E", 0.125), ("F", 0.125), ("A", 0.0625), ("B", 0.0625)],
        [("C", 0.125), ("D", 0.125)],
        [("X", 0.125), ("E", 0.0625), ("F", 0.0625), ("A", 0.03125), ("B", 0.03125)],
    ]
    # Независимые численные эталоны каждого transition, не вызов проверяемой формулы.
    even = [("C", "A", 0.5, 0.125), ("C", "X", 1.0, 0.25), ("C", "E", 1.0, 0.25),
            ("D", "B", 0.5, 0.125), ("D", "X", 1.0, 0.25), ("D", "F", 1.0, 0.25)]
    odd = [("A", "C", 1.0, 0.0625), ("B", "D", 1.0, 0.0625),
           ("X", "C", 0.5, 0.125), ("X", "D", 0.5, 0.125),
           ("E", "C", 0.5, 0.0625), ("F", "D", 0.5, 0.0625)]
    transition_rows = [[], [("A", "C", 1.0, 0.5), ("B", "D", 1.0, 0.5)], even, odd,
                       [(s, t, w, v / 2) for s, t, w, v in even],
                       [(s, t, w, v / 2) for s, t, w, v in odd],
                       [(s, t, w, v / 4) for s, t, w, v in even]]
    traces = result["traces"]
    assert len(traces) == 7
    for step, trace in enumerate(traces):
        assert trace["step"] == step
        assert trace["candidates"] == [dict(id=str(ids[n]), activation=v, kept=True)
                                       for n, v in expected[step]]
        assert trace["kept"] == [str(ids[n]) for n, _ in expected[step]]
        assert trace["pruned"] == []
        previous = dict(expected[step - 1]) if step else {}
        assert trace["sources"] == [dict(id=str(ids[n]), activation=previous[n])
                                    for n in sorted(previous, key=lambda n: ids[n])]
        assert trace["transitions"] == [dict(source=str(ids[s]), target=str(ids[t]),
                                            source_activation=previous[s], strength=1.0,
                                            route_weight=w, decay=0.5, contribution=v)
                                        for s, t, w, v in transition_rows[step]]
        totals = {}
        for transition in trace["transitions"]:
            target = names[transition["target"]]
            totals[target] = totals.get(target, 0.0) + transition["contribution"]
        if step:
            assert totals == dict(expected[step])
        if step >= 3:
            assert dict(expected[step]) == {n: v / 2 for n, v in expected[step - 2]}
    assert traces[2]["candidates"][0]["id"] == str(ids["X"])
    assert traces[2]["candidates"][0]["activation"] > traces[2]["candidates"][1]["activation"]
    assert result["activation"] == {str(ids[n]): v for n, v in expected[6]}
    assert result["step"] == 6 and result["trace"] == traces[6]
    assert result["parameters"] == dict(decay=0.5, max_active=7, max_steps=6)
    assert run_directional(graph, weights["asymmetric_traversal"], **definition.run.model_dump()) == result
    assert structure(graph) == before


def test_route_weights_require_both_existing_directions_and_finite_nonnegative_values():
    definition, graph, _, scenarios = setup()
    before = structure(graph)
    weights = scenarios["asymmetric_traversal"]
    pair = next(iter(weights))
    invalid_maps = [{k: v for k, v in weights.items() if k != pair},
                    {**weights, (pair[0], pair[0]): 1.0}]
    invalid_maps.extend({**weights, pair: value} for value in (-0.5, float("nan"), float("inf"), True))
    for invalid in invalid_maps:
        with pytest.raises(ValueError):
            run_directional(graph, invalid, **definition.run.model_dump())
    assert structure(graph) == before
