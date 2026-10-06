"""Отдельный положительный fixture и воспроизводимый эксперимент M2."""

import json
from uuid import UUID

from .activation import Activation
from .graph import ConceptId, Graph


def build_m2_fixture() -> tuple[Graph, dict[ConceptId, str]]:
    graph = Graph()
    ids = [graph.create_concept(UUID(int=i)).id for i in range(101, 106)]
    labels = dict(zip(ids, ("А", "Б", "В", "Г", "Д")))
    for a, b, strength in ((0, 2, 1.0), (1, 2, 0.5), (0, 3, 0.5),
                           (1, 4, 0.5), (2, 3, 0.5), (3, 4, 0.5)):
        graph.create_connection(ids[a], ids[b], strength)
    return graph, labels


def experiment() -> dict:
    graph, labels = build_m2_fixture()
    runtime = Activation(graph)
    runtime.start({UUID(int=101): 1.0, UUID(int=102): 1.0},
                  decay=0.5, max_steps=3, max_active=2)
    runtime.run()
    return {"labels": {str(cid): label for cid, label in labels.items()}, **runtime.snapshot()}


if __name__ == "__main__":
    print(json.dumps(experiment(), ensure_ascii=False, indent=2))
