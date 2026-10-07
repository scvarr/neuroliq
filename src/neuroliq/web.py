"""Единый Graph Lab: редактор definition и отдельный Python runtime."""

from collections.abc import Mapping
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .activation import Activation
from .experiment import ExperimentDefinition
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


def create_app(definition: ExperimentDefinition | None = None, *, workspace_path=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    static = Path(__file__).with_name("static")
    definition = ExperimentDefinition.from_json((definition or ExperimentDefinition.empty()).to_json())
    graph, labels = definition.build()
    runtime = Activation(graph)
    lock = Lock()

    @app.get("/api/experiment")
    def get_experiment():
        with lock:
            return definition.model_dump(mode="json")

    @app.get("/api/experiment/export")
    def export_experiment():
        with lock:
            return Response(definition.to_json(), media_type="application/json",
                            headers={"Content-Disposition": 'attachment; filename="experiment.neuroliq.json"'})

    @app.put("/api/experiment")
    async def replace_experiment(request: Request):
        nonlocal definition, graph, labels, runtime
        try:
            replacement = ExperimentDefinition.from_json((await request.body()).decode("utf-8"))
            new_graph, new_labels = replacement.build()
        except (ValueError, TypeError, OverflowError) as error:
            raise HTTPException(422, str(error)) from error
        with lock:
            definition, graph, labels = replacement, new_graph, new_labels
            runtime = Activation(graph)
            return definition.model_dump(mode="json")

    @app.get("/api/activation")
    def get_activation():
        with lock:
            return runtime.snapshot()

    @app.post("/api/activation/{command}")
    def command_activation(command: str):
        if command not in ("start", "reset", "step", "run"):
            raise HTTPException(404, "Неизвестная команда")
        with lock:
            try:
                if command == "start" or (command != "reset" and runtime.snapshot()["parameters"] is None):
                    run = definition.run
                    runtime.start(run.seeds, decay=run.decay, max_steps=run.max_steps,
                                  max_active=run.max_active)
                if command != "start":
                    getattr(runtime, command)()
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            return runtime.snapshot()

    @app.get("/api/graph")
    def get_graph():
        with lock:
            return graph_projection(graph, labels)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    from .lexical_api import install_lexical_api
    install_lexical_api(app, workspace_path)
    from .thought_api import install_thought_api
    install_thought_api(app, workspace_path)
    return app


app = create_app()
