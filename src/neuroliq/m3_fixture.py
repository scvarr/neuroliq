"""Контролируемое структурное пересечение M3 на неизменной математике M2."""

import json
from uuid import UUID

from .activation import Activation
from .graph import ConceptId, Graph


def build_m3_fixture() -> tuple[Graph, dict[ConceptId, str]]:
    graph = Graph()
    ids = [graph.create_concept(UUID(int=i)).id for i in range(201, 206)]
    labels = dict(zip(ids, ("СТОЛИЦА", "ФРАНЦИЯ", "ПАРИЖ", "ЛОНДОН", "ЛИОН")))
    for a, b in ((0, 2), (0, 3), (1, 2), (1, 4)):
        graph.create_connection(ids[a], ids[b], 1.0)
    return graph, labels


def observer_config() -> dict:
    """Параметры и seeds сценариев; вычисления выполняет только Activation."""
    return {
        "title": "Простое извлечение M3",
        "parameters": dict(decay=0.5, max_active=5, max_steps=1),
        "scenarios": [
            {"name": name, "seeds": {str(UUID(int=i)): 1.0 for i in ids}}
            for name, ids in (("СТОЛИЦА", (201,)), ("ФРАНЦИЯ", (202,)),
                              ("СТОЛИЦА + ФРАНЦИЯ", (201, 202)))
        ],
    }


def experiment() -> dict:
    graph, labels = build_m3_fixture()
    config = observer_config()
    runtime = Activation(graph)
    runs = []
    for scenario in config["scenarios"]:
        runtime.start({UUID(cid): value for cid, value in scenario["seeds"].items()},
                      **config["parameters"])
        runtime.run()
        runs.append({"name": scenario["name"], **runtime.snapshot()})
    return {"labels": {str(cid): label for cid, label in labels.items()}, "runs": runs}


if __name__ == "__main__":
    print(json.dumps(experiment(), ensure_ascii=False, indent=2))
