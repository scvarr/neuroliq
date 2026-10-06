"""Локальный наблюдатель: проекция структуры через публичный API ядра."""

from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .fixture import build_fixture
from .graph import ConceptId, Graph


def graph_projection(graph: Graph, labels: Mapping[ConceptId, str]) -> dict:
    """Прочитать структуру; метки принадлежат только web-представлению."""
    return {
        "concepts": [
            {
                "id": str(concept.id),
                "label": labels.get(concept.id, str(concept.id)),
                "neighbors": [str(neighbor) for neighbor in graph.neighbors(concept.id)],
            }
            for concept in graph.concepts()
        ],
        "connections": [
            {
                "concept_a": str(connection.concept_a),
                "concept_b": str(connection.concept_b),
                "strength": connection.strength,
            }
            for connection in graph.connections()
        ],
    }


def create_app(graph: Graph, labels: Mapping[ConceptId, str]) -> FastAPI:
    """Наблюдать переданный in-memory граф без операций записи."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    static = Path(__file__).with_name("static")

    @app.get("/api/graph")
    def get_graph() -> dict:
        return graph_projection(graph, labels)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


app = create_app(*build_fixture())
