"""Постоянная структура графа в памяти без вычислительной динамики."""

from dataclasses import dataclass
from math import isfinite
from uuid import UUID, uuid4

ConceptId = UUID


@dataclass(frozen=True, slots=True)
class Concept:
    id: ConceptId

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("ConceptId должен быть UUID")


@dataclass(frozen=True, slots=True)
class Connection:
    concept_a: ConceptId
    concept_b: ConceptId
    strength: float

    def __post_init__(self) -> None:
        if not isinstance(self.concept_a, UUID) or not isinstance(self.concept_b, UUID):
            raise TypeError("Концы связи должны быть ConceptId")
        if self.concept_a == self.concept_b:
            raise ValueError("Связь концепта с самим собой запрещена")
        if isinstance(self.strength, bool) or not isinstance(self.strength, (int, float)):
            raise TypeError("Сила связи должна быть числом int или float")
        try:
            strength = float(self.strength)
        except OverflowError as error:
            raise ValueError("Сила связи должна быть конечным числом") from error
        if not isfinite(strength):
            raise ValueError("Сила связи должна быть конечным числом")
        object.__setattr__(self, "strength", strength)


class Graph:
    """Неориентированный граф; порядок чтения определяется порядком создания."""

    def __init__(self) -> None:
        self._concepts: dict[ConceptId, Concept] = {}
        self._connections: dict[tuple[ConceptId, ConceptId], Connection] = {}
        self._neighbors: dict[ConceptId, dict[ConceptId, None]] = {}

    def create_concept(self, concept_id: ConceptId | None = None) -> Concept:
        """Создать концепт; явный ID позволяет воспроизводить искусственные графы."""
        concept = Concept(uuid4() if concept_id is None else concept_id)
        if concept.id in self._concepts:
            raise ValueError("ConceptId уже существует в графе")
        self._concepts[concept.id] = concept
        self._neighbors[concept.id] = {}
        return concept

    def get_concept(self, concept_id: ConceptId) -> Concept | None:
        return self._concepts.get(concept_id)

    @staticmethod
    def _pair(a: ConceptId, b: ConceptId) -> tuple[ConceptId, ConceptId]:
        return (a, b) if a.int <= b.int else (b, a)

    def create_connection(
        self, concept_a: ConceptId, concept_b: ConceptId, strength: float
    ) -> Connection:
        connection = Connection(concept_a, concept_b, strength)
        for concept_id in (concept_a, concept_b):
            if concept_id not in self._concepts:
                raise KeyError("Концепт отсутствует в графе", concept_id)
        pair = self._pair(concept_a, concept_b)
        if pair in self._connections:
            raise ValueError("Связь между этой парой концептов уже существует")
        connection = Connection(*pair, connection.strength)
        self._connections[pair] = connection
        self._neighbors[concept_a][concept_b] = None
        self._neighbors[concept_b][concept_a] = None
        return connection

    def get_connection(
        self, concept_a: ConceptId, concept_b: ConceptId
    ) -> Connection | None:
        return self._connections.get(self._pair(concept_a, concept_b))

    def neighbors(self, concept_id: ConceptId) -> tuple[ConceptId, ...]:
        return tuple(self._neighbors[concept_id])

    def concepts(self) -> tuple[Concept, ...]:
        return tuple(self._concepts.values())

    def connections(self) -> tuple[Connection, ...]:
        return tuple(self._connections.values())
