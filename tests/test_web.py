from dataclasses import fields
from uuid import UUID

from fastapi.testclient import TestClient

from neuroliq.graph import Concept, Graph
from neuroliq.fixture import build_fixture
from neuroliq.web import create_app, graph_projection


def test_projection_preserves_fixture_structure_and_strength():
    graph, labels = build_fixture()
    before = (graph.concepts(), graph.connections())
    projection = graph_projection(graph, labels)
    assert len(projection["concepts"]) == 5
    assert len(projection["connections"]) == 4
    assert projection["concepts"] == [
        {"id": str(c.id), "label": labels[c.id],
         "neighbors": [str(n) for n in graph.neighbors(c.id)]}
        for c in graph.concepts()
    ]
    assert projection["connections"] == [
        {"concept_a": str(c.concept_a), "concept_b": str(c.concept_b),
         "strength": c.strength}
        for c in graph.connections()
    ]
    isolated = next(c for c in projection["concepts"] if c["id"] == str(UUID(int=5)))
    assert isolated == {"id": str(UUID(int=5)), "label": "Изолированный", "neighbors": []}
    assert (graph.concepts(), graph.connections()) == before


def test_labels_are_external_and_missing_label_falls_back_to_id():
    graph, labels = build_fixture()
    concept = graph.concepts()[0]
    before = graph.concepts()
    labels[concept.id] = "Другая внешняя метка"
    assert graph_projection(graph, labels)["concepts"][0]["label"] == labels[concept.id]
    assert graph_projection(graph, {})["concepts"][0]["label"] == str(concept.id)
    assert [field.name for field in fields(Concept)] == ["id"]
    assert not hasattr(concept, "label")
    assert graph.concepts() == before


def test_endpoint_returns_expected_structure_and_reads_live_graph():
    graph, labels = build_fixture()
    with TestClient(create_app(graph, labels)) as client:
        response = client.get("/api/graph")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert response.json() == graph_projection(graph, labels)
        assert set(response.json()) == {"concepts", "connections"}
        added = graph.create_concept()
        labels[added.id] = "Добавлен через API ядра"
        assert client.get("/api/graph").json()["concepts"][-1] == {
            "id": str(added.id), "label": labels[added.id], "neighbors": []
        }
        assert client.post("/api/graph", json={}).status_code == 405


def test_page_and_local_assets_are_served():
    with TestClient(create_app(Graph(), {})) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert '<html lang="ru">' in response.text
        for path in ("style.css", "app.js", "vendor/cytoscape.min.js"):
            assert client.get(f"/static/{path}").status_code == 200
