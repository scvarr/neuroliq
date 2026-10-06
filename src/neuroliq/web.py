"""Локальный наблюдатель: проекция структуры через публичный API ядра."""

from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .activation import Activation
from .m2_fixture import build_m2_fixture
from .m3_fixture import build_m3_fixture, observer_config
from .m4_fixture import build_m4_fixture, observer_config as m4_observer_config
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


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seeds: dict[UUID, Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]] = Field(min_length=1)
    decay: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)
    max_steps: int = Field(ge=0, strict=True)
    max_active: int = Field(ge=1, strict=True)


def create_app(graph: Graph, labels: Mapping[ConceptId, str], *,
               experiment_config: dict | None = None) -> FastAPI:
    """Общий локальный runtime приложения; постоянный граф только читается."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    static = Path(__file__).with_name("static")
    runtime = Activation(graph)
    lock = Lock()

    @app.get("/api/experiment")
    def get_experiment() -> dict:
        return experiment_config if experiment_config is not None else {
            "title": "Активация M2",
            "parameters": dict(decay=0.5, max_active=2, max_steps=3),
            "scenarios": [],
        }

    @app.get("/api/activation")
    def get_activation() -> dict:
        with lock:
            return runtime.snapshot()

    @app.post("/api/activation/start")
    def start_activation(request: StartRequest) -> dict:
        with lock:
            try:
                runtime.start(request.seeds, decay=request.decay,
                              max_steps=request.max_steps, max_active=request.max_active)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            return runtime.snapshot()

    @app.post("/api/activation/{command}")
    def command_activation(command: str) -> dict:
        if command not in ("reset", "step", "run"):
            raise HTTPException(404, "Неизвестная команда")
        with lock:
            try:
                getattr(runtime, command)()
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            return runtime.snapshot()

    @app.get("/api/graph")
    def get_graph() -> dict:
        return graph_projection(graph, labels)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


app = create_app(*build_m2_fixture())
m3_app = create_app(*build_m3_fixture(), experiment_config=observer_config())

m4_app = create_app(*build_m4_fixture(), experiment_config=m4_observer_config())
