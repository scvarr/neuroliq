from collections import defaultdict
from uuid import UUID

from fastapi.testclient import TestClient

from neuroliq.activation import Activation
from neuroliq.graph import Graph
from neuroliq.m4_fixture import build_m4_fixture, experiment, observer_config
from neuroliq.web import create_app, m4_app


def structure(graph):
    return (graph.concepts(), graph.connections(),
            tuple((c.id, graph.neighbors(c.id)) for c in graph.concepts()))


def test_fixture_has_exact_structure_equal_strength_and_two_step_paths():
    graph, labels = build_m4_fixture()
    assert labels == dict(zip((UUID(int=i) for i in range(301, 308)), "ABCDXEF"))
    ids = {label: cid for cid, label in labels.items()}
    assert {c.id for c in graph.concepts()} == set(labels)
    assert len(graph.connections()) == 6
    assert {frozenset((labels[c.concept_a], labels[c.concept_b]))
            for c in graph.connections()} == {frozenset(pair) for pair in
                                               ("AC", "CX", "XD", "DB", "CE", "DF")}
    assert {c.strength for c in graph.connections()} == {1.0}
    for seed, bridge in (("A", "C"), ("B", "D")):
        assert graph.get_connection(ids[seed], ids["X"]) is None
        assert graph.get_connection(ids[seed], ids[bridge]) is not None
        assert graph.get_connection(ids[bridge], ids["X"]) is not None
    assert set(graph.neighbors(ids["X"])) == {ids["C"], ids["D"]}


def test_three_runs_full_trace_aggregation_and_return_wave():
    result = experiment()
    labels = result["labels"]
    expected = [
        [{"A": 1.0}, {"C": 0.5}, {"A": 0.25, "X": 0.25, "E": 0.25}],
        [{"B": 1.0}, {"D": 0.5}, {"B": 0.25, "X": 0.25, "F": 0.25}],
        [{"A": 1.0, "B": 1.0}, {"C": 0.5, "D": 0.5},
         {"X": 0.5, "A": 0.25, "B": 0.25, "E": 0.25, "F": 0.25}],
    ]
    for run, steps in zip(result["runs"], expected, strict=True):
        assert run["parameters"] == dict(decay=0.5, max_steps=2, max_active=7)
        assert run["step"] == 2
        assert len(run["traces"]) == 3
        for number, (trace, values) in enumerate(zip(run["traces"], steps, strict=True)):
            assert trace["step"] == number
            assert {labels[c["id"]]: c["activation"] for c in trace["candidates"]} == values
            assert not trace["pruned"]
            assert all(c["kept"] for c in trace["candidates"])
            assert trace["kept"] == [c["id"] for c in trace["candidates"]]
            if number == 0:
                assert trace["sources"] == trace["transitions"] == []
                continue
            assert {labels[s["id"]]: s["activation"] for s in trace["sources"]} == steps[number - 1]
            totals = defaultdict(float)
            for t in trace["transitions"]:
                assert t["source_activation"] == steps[number - 1][labels[t["source"]]]
                assert t["strength"] == 1.0
                assert t["decay"] == 0.5
                assert t["contribution"] == t["source_activation"] * 0.5
                totals[labels[t["target"]]] += t["contribution"]
            assert dict(totals) == values
        assert {labels[cid]: value for cid, value in run["activation"].items()} == steps[-1]
        leaders = {label for label, value in steps[-1].items() if value == max(steps[-1].values())}
        assert leaders == ({"X"} if run["name"] == "A + B" else set(steps[-1]))
    joint = result["runs"][2]
    assert [(labels[t["source"]], labels[t["target"]], t["contribution"])
            for t in joint["traces"][1]["transitions"]] == [("A", "C", 0.5), ("B", "D", 0.5)]
    assert [(labels[t["source"]], labels[t["target"]], t["contribution"])
            for t in joint["trace"]["transitions"]] == [
        ("C", "A", 0.25), ("C", "X", 0.25), ("C", "E", 0.25),
        ("D", "B", 0.25), ("D", "X", 0.25), ("D", "F", 0.25)]


def test_larger_width_does_not_change_any_candidates_or_transitions():
    graph, _ = build_m4_fixture()
    runtime = Activation(graph)
    for scenario, run in zip(observer_config()["scenarios"], experiment()["runs"], strict=True):
        runtime.start({UUID(cid): value for cid, value in scenario["seeds"].items()},
                      **{**observer_config()["parameters"], "max_active": 100})
        runtime.run()
        assert runtime.snapshot()["traces"] == run["traces"]
        assert runtime.snapshot()["activation"] == run["activation"]


def test_determinism_graph_unchanged_and_labels_do_not_affect_activation():
    expected = experiment()
    assert experiment() == expected
    graph, labels = build_m4_fixture()
    reverse = Graph()
    for c in reversed(graph.concepts()):
        reverse.create_concept(c.id)
    for c in reversed(graph.connections()):
        reverse.create_connection(c.concept_b, c.concept_a, c.strength)
    for tested in (graph, reverse):
        before = structure(tested)
        runtime = Activation(tested)
        labels.clear()
        for scenario, run in zip(observer_config()["scenarios"], expected["runs"], strict=True):
            runtime.start({UUID(cid): value for cid, value in reversed(list(scenario["seeds"].items()))},
                          **observer_config()["parameters"])
            runtime.run()
            runtime.step()
            assert runtime.snapshot() == {key: value for key, value in run.items() if key != "name"}
            assert structure(tested) == before
            runtime.reset()
            assert structure(tested) == before


def test_web_reproduces_all_scenarios_on_one_unchanged_graph():
    graph, labels = build_m4_fixture()
    before = structure(graph)
    config = observer_config()
    with TestClient(create_app(graph, labels, experiment_config=config)) as client:
        assert client.get("/api/experiment").json() == config
        projection = client.get("/api/graph").json()
        for scenario, run in zip(config["scenarios"], experiment()["runs"], strict=True):
            response = client.post("/api/activation/start", json={**config["parameters"], "seeds": scenario["seeds"]})
            assert response.status_code == 200
            assert response.json()["step"] == 0
            response = client.post("/api/activation/run")
            assert response.status_code == 200
            assert response.json() == {key: value for key, value in run.items() if key != "name"}
            assert client.get("/api/graph").json() == projection
        assert client.post("/api/activation/reset").json()["activation"] == {}
    assert structure(graph) == before


def test_m4_app_serves_fixture_and_history_control():
    with TestClient(m4_app) as client:
        assert client.get("/api/experiment").json() == observer_config()
        assert len(client.get("/api/graph").json()["concepts"]) == 7
        assert 'id="trace-step"' in client.get("/").text
