"""Переносимое описание эксперимента; метки и параметры находятся вне Graph."""

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .graph import ConceptId, Graph

Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Nonnegative = Annotated[Finite, Field(ge=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentConcept(Record):
    id: UUID
    label: str = Field(strict=True)


class ExperimentConnection(Record):
    concept_a: UUID
    concept_b: UUID
    strength: Finite


class RunConfiguration(Record):
    seeds: dict[UUID, Nonnegative]
    decay: Annotated[Nonnegative, Field(le=1)]
    max_active: int = Field(strict=True, ge=1)
    max_steps: int = Field(strict=True, ge=0)


class ExperimentDefinition(Record):
    format_version: int = Field(strict=True, ge=1, le=1)
    title: str = Field(strict=True)
    concepts: tuple[ExperimentConcept, ...]
    connections: tuple[ExperimentConnection, ...]
    run: RunConfiguration

    @model_validator(mode="after")
    def validate_structure(self):
        graph, _ = self.build()
        if any(graph.get_concept(cid) is None for cid in self.run.seeds):
            raise ValueError("Seed ссылается на отсутствующий концепт")
        return self

    def build(self) -> tuple[Graph, dict[ConceptId, str]]:
        graph = Graph()
        labels = {}
        for concept in self.concepts:
            graph.create_concept(concept.id)
            labels[concept.id] = concept.label
        for connection in self.connections:
            try:
                graph.create_connection(connection.concept_a, connection.concept_b,
                                        connection.strength)
            except KeyError as error:
                raise ValueError("Связь ссылается на отсутствующий концепт") from error
        return graph, labels

    @classmethod
    def empty(cls):
        return cls(format_version=1, title="Новый эксперимент", concepts=(), connections=(),
                   run=RunConfiguration(seeds={}, decay=0.5, max_active=10, max_steps=2))

    @classmethod
    def from_json(cls, source: str):
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Повторный JSON-ключ: {key}")
                result[key] = value
            return result
        try:
            data = json.loads(source, object_pairs_hook=unique_pairs)
        except json.JSONDecodeError as error:
            raise ValueError(f"Некорректный JSON: строка {error.lineno}, столбец {error.colno}") from error
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            problems = []
            for problem in error.errors():
                field = ".".join(map(str, problem["loc"])) or "experiment"
                reason = problem.get("ctx", {}).get("error", "неверный тип, диапазон или обязательное поле")
                problems.append(f"{field}: {reason}")
            raise ValueError("Некорректное описание эксперимента: " + "; ".join(problems)) from error

    @classmethod
    def load(cls, path: str | Path):
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False,
                          allow_nan=False, indent=2) + "\n"

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")
