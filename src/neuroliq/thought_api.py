"""API отдельного ручного Thought Workbench."""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .thought_workbench import Concept, Source, Thought, ThoughtStore, parse_snapshot


def install_thought_api(app, path=None):
    router = APIRouter(prefix="/api/thought-workbench")
    store = None

    def storage():
        nonlocal store
        if store is None:
            store = ThoughtStore(path or os.environ.get("NEUROLIQ_WORKSPACE_DB", "data/lexical-workspace.sqlite3"))
        return store

    @router.get("")
    def state():
        return storage().read().model_dump(mode="json")

    @router.get("/export")
    def export():
        return Response(storage().read().canonical(), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="thought-workbench.json"'})

    @router.put("")
    async def replace(request: Request):
        try:
            snapshot = parse_snapshot(await request.body())
            return storage().replace(snapshot).model_dump(mode="json")
        except (ValueError, TypeError, OverflowError) as error:
            raise HTTPException(422, str(error)) from error

    def install_collection(name, model):
        def mutate(record_id, record=None, create=False):
            try:
                return storage().mutate(name, record_id, record, create).model_dump(mode="json")
            except KeyError as error:
                raise HTTPException(404, str(error)) from error
            except (ValueError, TypeError, OverflowError) as error:
                raise HTTPException(422, str(error)) from error

        async def create(request: Request):
            try:
                record = model.model_validate(await request.json())
            except (ValueError, TypeError) as error:
                raise HTTPException(422, str(error)) from error
            return mutate(record.id, record, True)

        async def update(record_id: str, request: Request):
            try:
                record = model.model_validate(await request.json())
                if record.id != record_id:
                    raise ValueError("ID записи нельзя изменять")
            except (ValueError, TypeError) as error:
                raise HTTPException(422, str(error)) from error
            return mutate(record_id, record)

        def delete(record_id: str):
            return mutate(record_id)

        router.add_api_route(f"/{name}", create, methods=["POST"], status_code=201)
        router.add_api_route(f"/{name}/{{record_id}}", update, methods=["PUT"])
        router.add_api_route(f"/{name}/{{record_id}}", delete, methods=["DELETE"])

    for name, model in (("concepts", Concept), ("sources", Source), ("thoughts", Thought)):
        install_collection(name, model)
    app.include_router(router)

    @app.get("/thought-workbench", include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).with_name("static") / "thought-workbench.html")
