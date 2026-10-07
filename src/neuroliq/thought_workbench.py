"""Ручные конструкции мыслей: отдельный контракт и атомарное SQLite-хранение."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Identified(Record):
    id: str

    @field_validator("id")
    @classmethod
    def opaque_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("ID должен быть UUID в канонической записи")
        return value


class Concept(Identified):
    annotation: str


class Source(Identified):
    text: str
    context: str = ""


class Element(Identified):
    kind: Literal["concept", "literal"]
    concept_id: str | None = None
    value: str | None = None
    annotation: str = ""

    @model_validator(mode="after")
    def variant(self):
        if self.kind == "concept" and (self.concept_id is None or self.value is not None):
            raise ValueError("Элемент concept требует concept_id и не содержит value")
        if self.kind == "literal" and self.concept_id is not None:
            raise ValueError("Элемент literal не содержит concept_id")
        if self.kind == "literal" and self.value is None:
            raise ValueError("Элемент literal требует текстовое value")
        return self


class Link(Record):
    source: str
    target: str


class Thought(Identified):
    source_id: str
    annotation: str = ""
    elements: list[Element] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)

    @model_validator(mode="after")
    def local_structure(self):
        ids = unique_ids(self.elements)
        pairs = [(link.source, link.target) for link in self.links]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Повторная directed link")
        if any(a not in ids or b not in ids for a, b in pairs):
            raise ValueError("Концы связи должны принадлежать этой мысли")
        return self


def unique_ids(records):
    ids = {record.id for record in records}
    if len(ids) != len(records):
        raise ValueError("Повторный ID")
    return ids


class Snapshot(Record):
    format: Literal["neuroliq.thought-workbench"] = "neuroliq.thought-workbench"
    format_version: Literal[1] = 1
    concepts: list[Concept] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    thoughts: list[Thought] = Field(default_factory=list)

    @field_validator("format_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("Версия должна быть целым числом")
        return value

    @model_validator(mode="after")
    def references(self):
        concepts, sources = unique_ids(self.concepts), unique_ids(self.sources)
        unique_ids(self.thoughts)
        for thought in self.thoughts:
            if thought.source_id not in sources:
                raise ValueError("Источник мысли отсутствует")
            if any(e.kind == "concept" and e.concept_id not in concepts for e in thought.elements):
                raise ValueError("Reusable concept отсутствует")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        for name in ("concepts", "sources", "thoughts"):
            data[name].sort(key=lambda record: record["id"])
        for thought in data["thoughts"]:
            thought["elements"].sort(key=lambda record: record["id"])
            thought["links"].sort(key=lambda link: (link["source"], link["target"]))
        return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def parse_snapshot(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Повторный ключ JSON")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Недопустимая константа JSON: {value}")

    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(data, dict) or not {"format", "format_version", "concepts", "sources", "thoughts"} <= data.keys():
        raise ValueError("Требуется полный versioned snapshot")
    snapshot = Snapshot.model_validate(data)
    snapshot.canonical()
    return snapshot


class ThoughtStore:
    """Только таблицы tw_*; каждая запись и замена целиком транзакционны."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tw_concepts(id TEXT PRIMARY KEY, annotation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tw_sources(id TEXT PRIMARY KEY, text TEXT NOT NULL, context TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tw_thoughts(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES tw_sources(id), annotation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tw_elements(thought_id TEXT NOT NULL REFERENCES tw_thoughts(id), id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('concept','literal')), concept_id TEXT REFERENCES tw_concepts(id), value TEXT NOT NULL, annotation TEXT NOT NULL, PRIMARY KEY(thought_id,id));
                CREATE TABLE IF NOT EXISTS tw_links(thought_id TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, PRIMARY KEY(thought_id,source,target), FOREIGN KEY(thought_id,source) REFERENCES tw_elements(thought_id,id), FOREIGN KEY(thought_id,target) REFERENCES tw_elements(thought_id,id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _read(self, db):
        thoughts = [dict(row) for row in db.execute("SELECT * FROM tw_thoughts")]
        for thought in thoughts:
            thought["elements"] = []
            for row in db.execute("SELECT id,kind,concept_id,value,annotation FROM tw_elements WHERE thought_id=?", (thought["id"],)):
                element = dict(row)
                element["value"] = json.loads(element["value"])
                thought["elements"].append(element)
            thought["links"] = [dict(row) for row in db.execute("SELECT source,target FROM tw_links WHERE thought_id=?", (thought["id"],))]
        return Snapshot(concepts=[dict(row) for row in db.execute("SELECT * FROM tw_concepts")],
                        sources=[dict(row) for row in db.execute("SELECT * FROM tw_sources")], thoughts=thoughts)

    def read(self):
        with self.connect() as db:
            db.execute("BEGIN")
            return self._read(db)

    def _write(self, db, snapshot):
        for table in ("tw_links", "tw_elements", "tw_thoughts", "tw_sources", "tw_concepts"):
            db.execute(f"DELETE FROM {table}")
        db.executemany("INSERT INTO tw_concepts VALUES (?,?)", [(c.id, c.annotation) for c in snapshot.concepts])
        db.executemany("INSERT INTO tw_sources VALUES (?,?,?)", [(s.id, s.text, s.context) for s in snapshot.sources])
        for t in snapshot.thoughts:
            db.execute("INSERT INTO tw_thoughts VALUES (?,?,?)", (t.id, t.source_id, t.annotation))
            db.executemany("INSERT INTO tw_elements VALUES (?,?,?,?,?,?)", [(t.id, e.id, e.kind, e.concept_id, json.dumps(e.value, ensure_ascii=False, allow_nan=False), e.annotation) for e in t.elements])
            db.executemany("INSERT INTO tw_links VALUES (?,?,?)", [(t.id, link.source, link.target) for link in t.links])

    def replace(self, snapshot):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._write(db, snapshot)
        return snapshot

    def mutate(self, collection, record_id, record=None, create=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            data = self._read(db).model_dump(mode="json")
            records = data[collection]
            exists = any(r["id"] == record_id for r in records)
            if create and exists:
                raise ValueError("ID уже существует")
            if not create and not exists:
                raise KeyError("Запись не найдена")
            data[collection] = [r for r in records if r["id"] != record_id]
            if record is not None:
                data[collection].append(record.model_dump(mode="json"))
            snapshot = Snapshot.model_validate(data)
            snapshot.canonical()
            self._write(db, snapshot)
        return snapshot
