"""Локальная API-граница ревью lexical workspace."""

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .lexical_workspace import WorkspaceStore, build_workspace, family_view, mappings
from .m6_3_dataset import DATASET, REVISION, SHARD, SPLIT, validation_documents


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Document(StrictModel):
    reference: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=2_000_000)


class Batch(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    source: Literal["local", "dataset"] = "local"
    limit: int = Field(default=10_000, ge=1, le=100_000)
    documents: list[Document] = Field(default_factory=list, max_length=200)


class Decision(StrictModel):
    revision: int = Field(ge=0)
    action: Literal["accept", "reject", "split", "more"]
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=4000)
    selected: list[int] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)


def install_lexical_api(app, path=None):
    router = APIRouter(prefix="/api/lexical")
    store = None

    def storage():
        nonlocal store
        if store is None:
            store = WorkspaceStore(path or os.environ.get("NEUROLIQ_WORKSPACE_DB", "data/lexical-workspace.sqlite3"))
        return store

    def load(workspace_id):
        try:
            return storage().load(workspace_id)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @router.get("")
    def batches():
        return storage().list()

    @router.post("", status_code=201)
    def create(batch: Batch):
        if batch.source == "local" and not batch.documents:
            raise HTTPException(422, "Добавьте документы UTF-8")
        if batch.source == "dataset" and batch.documents:
            raise HTTPException(422, "Для корпуса документы не передаются")
        if batch.source == "local" and sum(len(d.text) for d in batch.documents) > 10_000_000:
            raise HTTPException(422, "Локальный батч ограничен 10 млн символов")
        documents = ([(d.reference, d.text) for d in batch.documents] if batch.source == "local" else
                     ((f"{DATASET}@{REVISION}/{SPLIT}/{SHARD}#row={i}", text)
                      for i, text in enumerate(validation_documents())))
        try:
            if batch.source == "dataset":
                corpus = f"{DATASET}@{REVISION}/{SPLIT}/{SHARD}"
                workspace = storage().create_dataset(documents, corpus, batch.limit, batch.title)
            else:
                workspace = build_workspace(documents, batch.limit, batch.title)
                storage().create(workspace)
        except (OSError, ImportError, ValueError) as error:
            raise HTTPException(422, f"Не удалось обработать корпус: {error}") from error
        finally:
            if hasattr(documents, "close"):
                documents.close()
        return {"id": workspace["id"]}

    @router.get("/{workspace_id}")
    def summary(workspace_id: str):
        w = load(workspace_id)
        return {k: v for k, v in w.items() if k not in ("sources", "occurrences", "events", "families")} | {
            "families": [{k: v for k, v in f.items() if k != "members"} | {"total": len(f["members"])}
                         for f in w["families"]], "mapping_count": sum(len(m["occurrence_ids"]) for m in mappings(w))}

    @router.get("/{workspace_id}/export")
    def export(workspace_id: str):
        w = load(workspace_id)
        return Response(json.dumps({"format_version": 1, "workspace": w, "mappings": mappings(w)}, ensure_ascii=False),
                        media_type="application/json", headers={"Content-Disposition": 'attachment; filename="lexical-workspace.json"'})

    @router.get("/{workspace_id}/sources/{source_id}")
    def source(workspace_id: str, source_id: int):
        w = load(workspace_id)
        if source_id < 0 or source_id >= len(w["sources"]):
            raise HTTPException(404, "Источник не найден")
        return w["sources"][source_id]

    @router.get("/{workspace_id}/families/{family_id}")
    def family(workspace_id: str, family_id: str):
        w = load(workspace_id)
        f = next((f for f in w["families"] if f["id"] == family_id), None)
        if f is None:
            raise HTTPException(404, "Семья не найдена")
        return family_view(w, f) | {"concept_ids": storage().form_concepts(f["forms"])}

    @router.post("/{workspace_id}/families/{family_id}")
    def decide(workspace_id: str, family_id: str, decision: Decision):
        try:
            w = storage().decide(workspace_id, family_id=family_id, **decision.model_dump())
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        return {"revision": w["revision"]}

    app.include_router(router)

    @app.get("/lexical", include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).with_name("static") / "lexical.html")

    @app.get("/l0", include_in_schema=False)
    def l0_page():
        return FileResponse(Path(__file__).with_name("static") / "l0.html")

    @app.get("/api/l0")
    def l0_stats():
        return storage().l0_stats()

    @app.get("/api/l0/dictionary")
    def dictionary(q: str = Query(default="", max_length=500), limit: int = Query(default=50, ge=1, le=200)):
        return storage().dictionary(q, limit)

    @app.get("/api/l0/concepts/{concept_id}")
    def neighborhood(concept_id: str, limit: int = Query(default=50, ge=1, le=200)):
        try:
            return storage().l0_neighborhood(concept_id, limit)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
