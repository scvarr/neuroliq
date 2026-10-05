"""Детерминированный искусственный граф с внешними диагностическими метками."""

from uuid import UUID

from .diagnostics import diagnostic_snapshot
from .graph import ConceptId, Graph


def build_fixture() -> tuple[Graph, dict[ConceptId, str]]:
    graph = Graph()
    ids = [graph.create_concept(UUID(int=value)).id for value in range(1, 6)]
    labels = dict(zip(ids, ("Альфа", "Бета", "Гамма", "Дельта", "Изолированный")))
    for a, b, strength in ((0, 1, 1.5), (0, 2, -2.0), (1, 2, 0.0), (2, 3, 12.25)):
        graph.create_connection(ids[a], ids[b], strength)
    return graph, labels


if __name__ == "__main__":
    graph, labels = build_fixture()
    print(diagnostic_snapshot(graph, labels))
