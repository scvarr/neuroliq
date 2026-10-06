import json
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from neuroliq.experiment import ExperimentDefinition
from neuroliq.graph import Concept, Graph
from neuroliq.web import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data():
    return json.loads((ROOT / "experiments/m3-simple-retrieval.neuroliq.json").read_text(encoding="utf-8"))


def test_exact_roundtrip_and_external_labels(data, tmp_path):
    data["connections"][0]["strength"] = 0.12345678901234566
    data["run"]["seeds"][data["concepts"][0]["id"]] = 1.2345678901234567
    data["run"].update(decay=0.375, max_active=3, max_steps=12)
    definition = ExperimentDefinition.from_json(json.dumps(data))
    graph, labels = definition.build()
    assert [c.id for c in graph.concepts()] == [UUID(c["id"]) for c in data["concepts"]]
    assert labels == {UUID(c["id"]): c["label"] for c in data["concepts"]}
    assert [f.name for f in fields(Concept)] == ["id"]
    for c in data["connections"]:
        assert graph.get_connection(UUID(c["concept_a"]), UUID(c["concept_b"])).strength == c["strength"]
    path = tmp_path / "roundtrip.neuroliq.json"
    definition.save(path)
    restored = ExperimentDefinition.load(path)
    assert restored == definition
    assert restored.model_dump(mode="json") == data
    assert restored.to_json() == definition.to_json()
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"format_version", "title", "concepts", "connections", "run"}


@pytest.mark.parametrize("change", [
    lambda d: d.update(format_version=True),
    lambda d: d.update(format_version=2),
    lambda d: d["concepts"].append(d["concepts"][0]),
    lambda d: d["concepts"][0].update(id="bad"),
    lambda d: d["connections"].append({**d["connections"][0], "concept_a": d["connections"][0]["concept_b"], "concept_b": d["connections"][0]["concept_a"]}),
    lambda d: d["connections"][0].update(concept_b=d["connections"][0]["concept_a"]),
    lambda d: d["connections"][0].update(concept_a=str(UUID(int=999))),
    lambda d: d["connections"][0].update(strength=True),
    lambda d: d["connections"][0].update(strength="1"),
    lambda d: d["connections"][0].update(strength=float("nan")),
    lambda d: d["connections"][0].update(strength=float("inf")),
    lambda d: d["connections"][0].update(strength=10**400),
    lambda d: d["connections"][0].update(type="semantic"),
    lambda d: d["run"]["seeds"].update({str(UUID(int=999)): 1}),
    lambda d: d["run"]["seeds"].update({d["concepts"][0]["id"]: -1}),
    lambda d: d["run"]["seeds"].update({d["concepts"][0]["id"]: True}),
    lambda d: d["run"].update(decay=float("nan")),
    lambda d: d["run"].update(decay=1.1),
    lambda d: d["run"].update(max_steps=-1),
    lambda d: d["run"].update(max_steps=1.0),
    lambda d: d["run"].update(max_active=False),
    lambda d: d["run"].update(max_active=0),
    lambda d: d.update(trace=[]),
])
def test_invalid_definition_rejected(data, change):
    change(data)
    with pytest.raises((ValueError, TypeError, OverflowError)):
        ExperimentDefinition.from_json(json.dumps(data))


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError, match="Повторный"):
        ExperimentDefinition.from_json('{"title":"a","title":"b"}')


def test_editor_rebuilds_graph_runtime_atomically(data):
    definition = ExperimentDefinition.model_validate(data)
    original, _ = definition.build()
    with TestClient(create_app(definition)) as client:
        assert client.post("/api/activation/run").json()["step"] == 1
        export = client.get("/api/experiment/export")
        assert ExperimentDefinition.from_json(export.text) == definition
        invalid = deepcopy(data)
        invalid["connections"][0]["concept_a"] = str(UUID(int=999))
        assert client.put("/api/experiment", json=invalid).status_code == 422
        assert client.get("/api/activation").json()["step"] == 1
        edited = deepcopy(data)
        removed = edited["concepts"].pop()["id"]
        edited["connections"] = [c for c in edited["connections"] if removed not in (c["concept_a"], c["concept_b"])]
        edited["concepts"][0]["label"] = "Новая метка"
        edited["connections"][0]["strength"] = 0.75
        assert client.put("/api/experiment", json=edited).status_code == 200
        state = client.get("/api/activation").json()
        assert state["traces"] == [] and state["parameters"] is None and state["activation"] == {}
        assert len(original.concepts()) == 5
        assert not hasattr(Graph, "delete_concept")
        graph = client.get("/api/graph").json()
        assert len(graph["concepts"]) == 4
        assert graph["concepts"][0]["label"] == "Новая метка"
        assert graph["connections"][0]["strength"] == 0.75
        assert client.post("/api/activation/step").json()["step"] == 1
        assert client.post("/api/activation/step").json()["step"] == 1
        assert client.post("/api/activation/reset").json()["traces"] == []
        assert client.get("/api/experiment").json() == edited
        assert client.put("/api/experiment", content=export.text).status_code == 200
        assert client.get("/api/activation").json()["traces"] == []


def test_empty_experiment_and_no_seed_run():
    with TestClient(create_app()) as client:
        assert client.get("/api/experiment").json() == ExperimentDefinition.empty().model_dump(mode="json")
        assert client.post("/api/activation/run").status_code == 422
        assert client.post("/api/activation/unknown").status_code == 404


def test_frontend_displays_python_trace_without_activation_formula():
    source = (ROOT / "src/neuroliq/static/app.js").read_text(encoding="utf-8")
    assert "t.contribution" in source and "state.traces" in source
    assert "source_activation *" not in source and "strength *" not in source
    assert "crypto.randomUUID()" in source


def test_compose_port_and_single_service():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert '127.0.0.1:${NEUROLIQ_PORT:-17890}:8000' in compose
    assert compose.count("build:") == 1
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert '"neuroliq.web:app"' in dockerfile
