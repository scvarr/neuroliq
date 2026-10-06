"""Точные traces, влияние выбора и неизменность постоянного графа M5.3."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from neuroliq.activation import Activation
from neuroliq.experiment import ExperimentDefinition
from neuroliq.m5_3 import run_transient


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments/m5-3-transient-direction-state.neuroliq.json"


def setup():
    definition = ExperimentDefinition.load(EXPERIMENT)
    graph, labels = definition.build()
    return definition, graph, {label: cid for cid, label in labels.items()}


@pytest.mark.parametrize("dynamic", [False, True])
def test_exact_full_trace(dynamic):
    definition, graph, ids = setup()
    result = run_transient(graph, dynamic=dynamic, **definition.run.model_dump())
    # Независимые численные эталоны: source, target, activation, strength, r, g, вклад.
    rows = ([[], [("A", "B", 1.0, 1.0, 0.0, 1.0, 0.5)],
             [("B", "A", 0.5, 1.0, 0.5, 0.5, 0.125),
              ("B", "C", 0.5, 0.75, 0.0, 1.0, 0.1875)],
             [("C", "B", 0.1875, 0.75, 0.5, 0.5, 0.03515625),
              ("C", "D", 0.1875, 1.0, 0.0, 1.0, 0.09375)]] if dynamic else
            [[], [("A", "B", 1.0, 1.0, 0.0, 1.0, 0.5)],
             [("B", "A", 0.5, 1.0, 0.0, 1.0, 0.25),
              ("B", "C", 0.5, 0.75, 0.0, 1.0, 0.1875)],
             [("A", "B", 0.25, 1.0, 0.0, 1.0, 0.125)]])
    ranked = ([[("A", 1.0)], [("B", 0.5)], [("C", 0.1875), ("A", 0.125)],
               [("D", 0.09375), ("B", 0.03515625)]] if dynamic else
              [[("A", 1.0)], [("B", 0.5)], [("A", 0.25), ("C", 0.1875)],
               [("B", 0.125)]])
    states = ([{}, {"BA": 0.5}, {"BA": 0.25, "CB": 0.5},
               {"BA": 0.125, "CB": 0.25, "DC": 0.5}] if dynamic else [{}] * 4)
    expected = []
    for step in range(4):
        chosen = ranked[step][0][0]
        previous = ranked[step - 1][0] if step else None
        expected.append(dict(
            step=step,
            sources=[dict(id=str(ids[previous[0]]), activation=previous[1])] if step else [],
            transitions=[dict(source=str(ids[s]), target=str(ids[t]), source_activation=a,
                              strength=strength, r=r, route_weight=g, decay=0.5,
                              contribution=c, kept=t == chosen)
                         for s, t, a, strength, r, g, c in rows[step]],
            candidates=[dict(id=str(ids[n]), activation=a, kept=n == chosen)
                        for n, a in ranked[step]],
            kept=[str(ids[chosen])], pruned=[str(ids[n]) for n, _ in ranked[step][1:]],
            transient_after_update=[dict(source=str(ids[s]), target=str(ids[t]),
                                         r=states[step].get(s + t, 0.0))
                                    for s, t in ("AB", "BA", "BC", "CB", "CD", "DC")]))
    assert result["traces"] == expected
    assert result["trace"] == expected[-1]
    assert result["step"] == 3
    assert result["activation"] == {str(ids[ranked[-1][0][0]]): ranked[-1][0][1]}
    assert result["parameters"] == dict(decay=0.5, max_steps=3, max_active=1,
                                        dynamic=dynamic, h=0.5, rho=0.5)
    if not dynamic:
        baseline = Activation(graph)
        baseline.start(**definition.run.model_dump())
        baseline.run()
        comparable = deepcopy(result)
        for name in ("dynamic", "h", "rho"):
            comparable["parameters"].pop(name)
        for trace in comparable["traces"]:
            trace.pop("transient_after_update")
            for transition in trace["transitions"]:
                for name in ("r", "route_weight", "kept"):
                    transition.pop(name)
        assert comparable == baseline.snapshot()


def test_routes_decay_only_selected_transition_and_unchanged_graph():
    definition, graph, ids = setup()
    before = deepcopy((graph.concepts(), graph.connections(),
                       tuple(graph.neighbors(c.id) for c in graph.concepts())))
    connections = graph.connections()
    assert len(graph.concepts()) == 4
    assert [(c.concept_a, c.concept_b, c.strength) for c in connections] == [
        (ids["A"], ids["B"], 1.0), (ids["B"], ids["C"], 0.75),
        (ids["C"], ids["D"], 1.0)]
    assert definition.run.model_dump() == dict(seeds={ids["A"]: 1.0}, decay=0.5,
                                             max_active=1, max_steps=3)
    results = [run_transient(graph, dynamic=d, **definition.run.model_dump())
               for d in (False, True)]
    names = {str(cid): name for name, cid in ids.items()}
    routes = [[names[t["kept"][0]] for t in result["traces"]] for result in results]
    assert routes == [list("ABAB"), list("ABCD")]
    dynamic = results[1]
    old_r = [next(row["r"] for row in t["transient_after_update"]
                  if row["source"] == str(ids["B"]) and row["target"] == str(ids["A"]))
             for t in dynamic["traces"][1:]]
    assert old_r == [0.5, 0.25, 0.125]
    # Отброшенные B→A и C→B не деформируют A→B и B→C; усиления нет.
    assert all(row["r"] == 0.0 for t in dynamic["traces"]
               for row in t["transient_after_update"]
               if (names[row["source"]], names[row["target"]]) in [("A", "B"), ("B", "C"), ("C", "D")])
    for d, result in zip((False, True), results):
        assert run_transient(graph, dynamic=d, **definition.run.model_dump()) == result
    assert (graph.concepts(), graph.connections(),
            tuple(graph.neighbors(c.id) for c in graph.concepts())) == before
    for c in connections:
        assert graph.get_connection(c.concept_a, c.concept_b) is c
        assert graph.get_connection(c.concept_b, c.concept_a) is c


def test_cli_reproduces_both_full_traces():
    definition, graph, ids = setup()
    output = subprocess.check_output([sys.executable, "-m", "neuroliq.m5_3"], cwd=ROOT)
    payload = json.loads(output)
    assert payload == json.loads((ROOT / "experiments/m5-3-trace.json").read_bytes())
    assert payload["labels"] == {str(cid): name for name, cid in ids.items()}
    assert payload["scenarios"] == {
        name: run_transient(graph, dynamic=d, **definition.run.model_dump())
        for name, d in (("control", False), ("dynamic", True))}


def test_experiment_rejects_multiple_sources_and_choices():
    definition, graph, ids = setup()
    parameters = definition.run.model_dump()
    for changes in (dict(max_active=2), dict(seeds={ids["A"]: 1.0, ids["B"]: 1.0}),
                    dict(max_active=True), dict(dynamic=1)):
        with pytest.raises(ValueError):
            run_transient(graph, **{**parameters, "dynamic": True, **changes})
