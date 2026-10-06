from collections import defaultdict
from dataclasses import fields
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from neuroliq.activation import Activation
from neuroliq.graph import Concept, Connection, Graph
from neuroliq.m2_fixture import build_m2_fixture, experiment
from neuroliq.web import create_app


def structure(graph):
    return (graph.concepts(), graph.connections(),
            tuple((c.id, graph.neighbors(c.id)) for c in graph.concepts()))


def start(runtime, **changes):
    parameters = dict(decay=0.5, max_steps=3, max_active=2)
    parameters.update(changes)
    runtime.start({UUID(int=101): 1, UUID(int=102): 1}, **parameters)


def test_experiment_formula_aggregation_pruning_and_no_retention():
    result = experiment()
    assert result == experiment()
    assert [list(t["activation"] for t in trace["candidates"]) for trace in result["traces"]] == [
        [1, 1], [0.75, 0.25, 0.25], [0.4375, 0.1875, 0.1875, 0.0625, 0.0625],
        [0.265625, 0.109375, 0.046875]]
    for trace in result["traces"][1:]:
        totals = defaultdict(float)
        sources = {s["id"]: s["activation"] for s in trace["sources"]}
        for transition in trace["transitions"]:
            assert transition["source_activation"] == sources[transition["source"]]
            assert transition["contribution"] == (transition["source_activation"] *
                                                   transition["strength"] * transition["decay"])
            totals[transition["target"]] += transition["contribution"]
        assert dict(totals) == {c["id"]: c["activation"] for c in trace["candidates"]}
        assert trace["kept"] == [c["id"] for c in trace["candidates"] if c["kept"]]
        assert trace["pruned"] == [c["id"] for c in trace["candidates"] if not c["kept"]]
    assert result["traces"][1]["pruned"] == [str(UUID(int=105))]
    assert result["activation"] == {str(UUID(int=103)): 0.265625, str(UUID(int=104)): 0.109375}


def test_graph_unchanged_and_reset_destroys_all_runtime_state():
    graph, _ = build_m2_fixture()
    before = structure(graph)
    runtime = Activation(graph)
    start(runtime)
    runtime.run()
    runtime.step()
    assert runtime.snapshot()["step"] == 3
    snapshot = runtime.snapshot()
    snapshot["traces"].clear()
    assert len(runtime.snapshot()["traces"]) == 4
    runtime.reset()
    assert runtime.snapshot() == dict(activation={}, parameters=None, step=-1, trace=None, traces=[])
    assert structure(graph) == before
    assert [f.name for f in fields(Concept)] == ["id"]
    assert [f.name for f in fields(Connection)] == ["concept_a", "concept_b", "strength"]
    with pytest.raises(ValueError):
        runtime.step()


def test_decay_and_limits_and_multi_seed():
    graph, _ = build_m2_fixture()
    runtime = Activation(graph)
    start(runtime, decay=1, max_active=5, max_steps=1)
    runtime.run()
    assert runtime.snapshot()["activation"][str(UUID(int=103))] == 1.5
    start(runtime, max_steps=0, max_active=1)
    runtime.run()
    assert runtime.snapshot()["activation"] == {str(UUID(int=101)): 1}
    start(runtime, decay=0)
    runtime.step()
    assert all(value == 0 for value in runtime.snapshot()["activation"].values())


def test_determinism_independent_of_creation_and_seed_order():
    graph, labels = build_m2_fixture()
    reverse = Graph()
    for concept in reversed(graph.concepts()):
        reverse.create_concept(concept.id)
    for connection in reversed(graph.connections()):
        reverse.create_connection(connection.concept_b, connection.concept_a, connection.strength)
    runtime = Activation(reverse)
    runtime.start({UUID(int=102): 1, UUID(int=101): 1}, decay=0.5, max_active=2, max_steps=3)
    runtime.run()
    assert runtime.snapshot()["traces"] == experiment()["traces"]


@pytest.mark.parametrize("changes", [{"decay": float("nan")}, {"decay": -1}, {"decay": 2},
                                     {"max_active": 0}, {"max_steps": -1}, {"max_steps": True}])
def test_invalid_parameters_do_not_destroy_previous_run(changes):
    graph, _ = build_m2_fixture()
    runtime = Activation(graph)
    start(runtime)
    before = runtime.snapshot()
    with pytest.raises(ValueError):
        start(runtime, **changes)
    assert runtime.snapshot() == before


def test_invalid_seeds_and_overflow_are_atomic():
    graph, _ = build_m2_fixture()
    runtime = Activation(graph)
    for seeds in ({}, {UUID(int=999): 1}, {UUID(int=101): -1}, {UUID(int=101): float("inf")}):
        with pytest.raises(ValueError):
            runtime.start(seeds, decay=0.5, max_active=2, max_steps=3)
    huge = Graph()
    a, b = huge.create_concept().id, huge.create_concept().id
    huge.create_connection(a, b, 1e308)
    runtime = Activation(huge)
    runtime.start({a: 1e308}, decay=1, max_steps=1, max_active=2)
    before = runtime.snapshot()
    with pytest.raises(ValueError, match="Переполнение"):
        runtime.step()
    assert runtime.snapshot() == before


def test_web_commands_use_python_runtime_and_preserve_graph():
    graph, labels = build_m2_fixture()
    before = structure(graph)
    with TestClient(create_app(graph, labels)) as client:
        projection = client.get("/api/graph").json()
        assert client.post("/api/activation/step").status_code == 422
        request = dict(seeds={str(UUID(int=101)): 1, str(UUID(int=102)): 1},
                       decay=0.5, max_steps=3, max_active=2)
        assert client.post("/api/activation/start", json=request).json()["step"] == 0
        assert client.post("/api/activation/step").json()["trace"] == experiment()["traces"][1]
        assert client.post("/api/activation/run").json()["traces"] == experiment()["traces"]
        assert client.get("/api/activation").json()["step"] == 3
        assert client.post("/api/activation/start", json={**request, "max_steps": -1}).status_code == 422
        assert client.get("/api/activation").json()["step"] == 3
        assert client.post("/api/activation/reset").json()["activation"] == {}
        assert client.get("/api/graph").json() == projection
        script = client.get("/static/app.js").text
        assert 'request(button.id)' in script
        assert 'state.activation[node.id()]' in script
        assert 'contribution =' not in script
        assert 'source_activation *' not in script
    assert structure(graph) == before


def test_isolated_seed_has_no_retention_and_negative_strength_is_rejected():
    graph = Graph()
    a, b = graph.create_concept().id, graph.create_concept().id
    runtime = Activation(graph)
    runtime.start({a: 1}, decay=0.5, max_steps=2, max_active=1)
    runtime.run()
    assert runtime.snapshot()["activation"] == {}
    assert runtime.snapshot()["traces"][1]["sources"] == [{"id": str(a), "activation": 1}]
    assert runtime.snapshot()["traces"][1]["transitions"] == []
    graph.create_connection(a, b, -1)
    before = runtime.snapshot()
    with pytest.raises(ValueError, match="отрицательные"):
        runtime.start({a: 1}, decay=0.5, max_steps=2, max_active=1)
    assert runtime.snapshot() == before
