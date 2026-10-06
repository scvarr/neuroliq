"""Ограниченная проверка периодического эха M5.1 на неизменном Activation M2."""

from pathlib import Path
from uuid import UUID

from neuroliq.activation import Activation
from neuroliq.experiment import ExperimentDefinition


EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"
M5_1 = EXPERIMENTS / "m5-1-backwave-echo.neuroliq.json"


def execute(definition, *, stepwise=False):
    graph, labels = definition.build()
    before = (graph.concepts(), graph.connections(),
              tuple(graph.neighbors(c.id) for c in graph.concepts()))
    runtime = Activation(graph)
    runtime.start(**definition.run.model_dump())
    if stepwise:
        for _ in range(6):
            runtime.step()
    else:
        runtime.run()
    assert (graph.concepts(), graph.connections(),
            tuple(graph.neighbors(c.id) for c in graph.concepts())) == before
    return runtime.snapshot(), {str(cid): label for cid, label in labels.items()}


def test_definition_preserves_m4_structure_and_fixed_contract(tmp_path):
    m4 = ExperimentDefinition.load(EXPERIMENTS / "m4-two-step-bridge.neuroliq.json")
    definition = ExperimentDefinition.load(M5_1)
    assert definition.format_version == m4.format_version == 1
    assert definition.concepts == m4.concepts
    assert definition.connections == m4.connections
    assert {c.id: c.label for c in definition.concepts} == {
        UUID(int=i): label for i, label in zip(range(301, 308), "ABCDXEF", strict=True)
    }
    labels = {c.id: c.label for c in definition.concepts}
    assert len(definition.connections) == 6
    assert {frozenset((labels[c.concept_a], labels[c.concept_b]))
            for c in definition.connections} == {
        frozenset(pair) for pair in ("AC", "CX", "XD", "DB", "CE", "DF")
    }
    assert all(c.strength == 1.0 for c in definition.connections)
    assert definition.run.model_dump() == {
        "seeds": {UUID(int=301): 1.0, UUID(int=302): 1.0},
        "decay": 0.5, "max_active": 7, "max_steps": 6,
    }
    assert definition.run.model_dump(exclude={"max_steps"}) == m4.run.model_dump(
        exclude={"max_steps"})
    saved = tmp_path / M5_1.name
    definition.save(saved)
    restored = ExperimentDefinition.load(saved)
    assert restored == definition
    assert execute(restored) == execute(definition)


def test_actual_trace_has_exact_period_two_without_attenuation():
    snapshot, labels = execute(ExperimentDefinition.load(M5_1))
    odd = [("C", 0.5), ("D", 0.5)]
    even = [("X", 0.5), ("A", 0.25), ("B", 0.25), ("E", 0.25), ("F", 0.25)]
    expected = [[("A", 1.0), ("B", 1.0)], odd, even, odd, even, odd, even]
    transitions_1 = [("A", "C", 0.5), ("B", "D", 0.5)]
    transitions_even = [
        ("C", "A", 0.25), ("C", "X", 0.25), ("C", "E", 0.25),
        ("D", "B", 0.25), ("D", "X", 0.25), ("D", "F", 0.25),
    ]
    transitions_odd = [
        ("A", "C", 0.125), ("B", "D", 0.125),
        ("X", "C", 0.25), ("X", "D", 0.25),
        ("E", "C", 0.125), ("F", "D", 0.125),
    ]
    expected_transitions = [[], transitions_1, transitions_even, transitions_odd,
                            transitions_even, transitions_odd, transitions_even]
    traces = snapshot["traces"]
    assert snapshot["parameters"] == {"decay": 0.5, "max_active": 7, "max_steps": 6}
    assert snapshot["step"] == 6
    assert len(traces) == 7
    for number, trace in enumerate(traces):
        assert trace["step"] == number
        assert [(labels[c["id"]], c["activation"]) for c in trace["candidates"]] == expected[number]
        assert trace["pruned"] == []
        assert all(c["kept"] for c in trace["candidates"])
        assert trace["kept"] == [c["id"] for c in trace["candidates"]]
        assert [(labels[t["source"]], labels[t["target"]], t["contribution"])
                for t in trace["transitions"]] == expected_transitions[number]
        sources = {labels[s["id"]]: s["activation"] for s in trace["sources"]}
        assert sources == (dict(expected[number - 1]) if number else {})
        totals = {}
        for transition in trace["transitions"]:
            source, target = labels[transition["source"]], labels[transition["target"]]
            assert transition["source_activation"] == sources[source]
            assert transition["strength"] == 1.0
            assert transition["decay"] == 0.5
            assert transition["contribution"] == sources[source] * 0.5
            totals[target] = totals.get(target, 0.0) + transition["contribution"]
        if number:
            assert totals == dict(expected[number])
    assert traces[1]["candidates"] == traces[3]["candidates"] == traces[5]["candidates"]
    assert traces[2]["candidates"] == traces[4]["candidates"] == traces[6]["candidates"]
    assert traces[1]["candidates"] != traces[2]["candidates"]
    assert {labels[cid]: value for cid, value in snapshot["activation"].items()} == dict(even)
    assert snapshot["trace"] == traces[6]


def test_independent_runs_and_six_steps_reproduce_full_trace():
    definition = ExperimentDefinition.load(M5_1)
    expected = execute(definition)
    assert execute(ExperimentDefinition.load(M5_1)) == expected
    assert execute(definition, stepwise=True) == expected
