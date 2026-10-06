from collections import defaultdict
from uuid import UUID

from fastapi.testclient import TestClient

from neuroliq.activation import Activation
from neuroliq.graph import Graph
from neuroliq.m3_fixture import build_m3_fixture, experiment, observer_config
from neuroliq.web import create_app


def structure(graph):
    return (graph.concepts(), graph.connections(),
            tuple((c.id, graph.neighbors(c.id)) for c in graph.concepts()))


def test_fixture_has_exact_structure_and_equal_strength():
    graph, labels = build_m3_fixture()
    assert labels == dict(zip((UUID(int=i) for i in range(201, 206)),
                             ("СТОЛИЦА", "ФРАНЦИЯ", "ПАРИЖ", "ЛОНДОН", "ЛИОН")))
    assert {c.id for c in graph.concepts()} == set(labels)
    assert len(graph.connections()) == 4
    assert {(labels[c.concept_a], labels[c.concept_b], c.strength)
            for c in graph.connections()} == {
        ("СТОЛИЦА", "ПАРИЖ", 1.0), ("СТОЛИЦА", "ЛОНДОН", 1.0),
        ("ФРАНЦИЯ", "ПАРИЖ", 1.0), ("ФРАНЦИЯ", "ЛИОН", 1.0)}


def test_three_runs_ties_unique_leader_and_only_two_contributions():
    result = experiment()
    labels = result["labels"]
    expected = [{"ПАРИЖ": 0.5, "ЛОНДОН": 0.5},
                {"ПАРИЖ": 0.5, "ЛИОН": 0.5},
                {"ПАРИЖ": 1.0, "ЛОНДОН": 0.5, "ЛИОН": 0.5}]
    for run, values in zip(result["runs"], expected, strict=True):
        assert run["parameters"] == dict(decay=0.5, max_steps=1, max_active=5)
        assert run["step"] == 1
        assert len(run["traces"]) == 2
        assert {labels[cid]: value for cid, value in run["activation"].items()} == values
        trace = run["trace"]
        assert all(not t["pruned"] for t in run["traces"])
        assert all(c["kept"] for c in trace["candidates"])
        assert {c["id"]: c["activation"] for c in trace["candidates"]} == run["activation"]
        leaders = [labels[c["id"]] for c in trace["candidates"]
                   if c["activation"] == max(values.values())]
        assert set(leaders) == {name for name, value in values.items() if value == max(values.values())}
        totals = defaultdict(float)
        for t in trace["transitions"]:
            assert (t["source_activation"], t["strength"], t["decay"], t["contribution"]) == (1, 1, 0.5, 0.5)
            totals[t["target"]] += t["contribution"]
        assert dict(totals) == run["activation"]
    joint = result["runs"][2]["trace"]
    assert [(labels[t["source"]], labels[t["target"]], t["contribution"])
            for t in joint["transitions"]] == [
        ("СТОЛИЦА", "ПАРИЖ", 0.5), ("СТОЛИЦА", "ЛОНДОН", 0.5),
        ("ФРАНЦИЯ", "ПАРИЖ", 0.5), ("ФРАНЦИЯ", "ЛИОН", 0.5)]
    assert [labels[s["id"]] for s in joint["sources"]] == ["СТОЛИЦА", "ФРАНЦИЯ"]
    assert joint["candidates"][0]["activation"] > joint["candidates"][1]["activation"]


def test_determinism_graph_unchanged_and_labels_do_not_affect_activation():
    expected = experiment()
    assert experiment() == expected
    graph, labels = build_m3_fixture()
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
    graph, labels = build_m3_fixture()
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
