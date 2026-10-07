"""Общий ручной граф ConceptId и упорядоченные маршруты мыслей."""

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


class Connection(Record):
    concept_a: str
    concept_b: str

    @model_validator(mode="after")
    def canonical_pair(self):
        self.concept_a, self.concept_b = sorted((self.concept_a, self.concept_b))
        return self


class Thought(Identified):
    source_id: str
    annotation: str = ""
    route: list[str] = Field(default_factory=list)


def unique_ids(records):
    ids = {record.id for record in records}
    if len(ids) != len(records):
        raise ValueError("Повторный ID")
    return ids


class Snapshot(Record):
    format: Literal["neuroliq.thought-workbench"] = "neuroliq.thought-workbench"
    format_version: Literal[2] = 2
    concepts: list[Concept] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
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
        pairs = {(c.concept_a, c.concept_b) for c in self.connections}
        if len(pairs) != len(self.connections):
            raise ValueError("Повторная глобальная связь")
        if any(a not in concepts or b not in concepts for a, b in pairs):
            raise ValueError("Концы глобальной связи должны существовать в каталоге")
        for thought in self.thoughts:
            if thought.source_id not in sources:
                raise ValueError("Источник мысли отсутствует")
            if any(concept_id not in concepts for concept_id in thought.route):
                raise ValueError("ConceptId маршрута отсутствует в каталоге")
            if any(tuple(sorted((a, b))) not in pairs for a, b in zip(thought.route, thought.route[1:])):
                raise ValueError("Между соседними шагами маршрута отсутствует глобальная связь")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        for name in ("concepts", "sources", "thoughts"):
            data[name].sort(key=lambda record: record["id"])
        data["connections"].sort(key=lambda c: (c["concept_a"], c["concept_b"]))
        result = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        result.encode("utf-8")
        return result


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
    if not isinstance(data, dict) or not {"format", "format_version", "concepts", "connections", "sources", "thoughts"} <= data.keys():
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
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tw_thoughts)")}
            if columns and "route" not in columns:
                # Незамерженный прежний контракт заменяется без переноса данных.
                for table in ("tw_links", "tw_elements", "tw_connections", "tw_thoughts", "tw_sources", "tw_concepts"):
                    db.execute(f"DROP TABLE IF EXISTS {table}")
            db.execute("CREATE TABLE IF NOT EXISTS tw_concepts(id TEXT PRIMARY KEY, annotation TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS tw_sources(id TEXT PRIMARY KEY, text TEXT NOT NULL, context TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS tw_connections(
                concept_a TEXT NOT NULL REFERENCES tw_concepts(id),
                concept_b TEXT NOT NULL REFERENCES tw_concepts(id),
                PRIMARY KEY(concept_a,concept_b), CHECK(concept_a <= concept_b))""")
            db.execute("""CREATE TABLE IF NOT EXISTS tw_thoughts(
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES tw_sources(id),
                annotation TEXT NOT NULL, route TEXT NOT NULL)""")

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
            thought["route"] = json.loads(thought["route"])
        return Snapshot(concepts=[dict(row) for row in db.execute("SELECT * FROM tw_concepts")],
                        connections=[dict(row) for row in db.execute("SELECT * FROM tw_connections")],
                        sources=[dict(row) for row in db.execute("SELECT * FROM tw_sources")], thoughts=thoughts)

    def read(self):
        with self.connect() as db:
            db.execute("BEGIN")
            return self._read(db)

    def _write(self, db, snapshot):
        for table in ("tw_thoughts", "tw_connections", "tw_sources", "tw_concepts"):
            db.execute(f"DELETE FROM {table}")
        db.executemany("INSERT INTO tw_concepts VALUES (?,?)", [(c.id, c.annotation) for c in snapshot.concepts])
        db.executemany("INSERT INTO tw_sources VALUES (?,?,?)", [(s.id, s.text, s.context) for s in snapshot.sources])
        db.executemany("INSERT INTO tw_connections VALUES (?,?)", [(c.concept_a, c.concept_b) for c in snapshot.connections])
        for t in snapshot.thoughts:
            db.execute("INSERT INTO tw_thoughts VALUES (?,?,?,?)", (t.id, t.source_id, t.annotation, json.dumps(t.route)))

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
            def key(r):
                return (r["concept_a"], r["concept_b"]) if collection == "connections" else r["id"]
            exists = any(key(r) == record_id for r in records)
            if create and exists:
                raise ValueError("ID уже существует")
            if not create and not exists:
                raise KeyError("Запись не найдена")
            data[collection] = [r for r in records if key(r) != record_id]
            if record is not None:
                data[collection].append(record.model_dump(mode="json"))
            snapshot = Snapshot.model_validate(data)
            snapshot.canonical()
            self._write(db, snapshot)
        return snapshot
