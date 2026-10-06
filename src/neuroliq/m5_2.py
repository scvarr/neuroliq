"""Отдельный пакетный эксперимент M5.2; не является общим runtime Neuroliq."""

import argparse
import json
from collections.abc import Mapping
from math import isfinite

from .activation import Activation, finite_nonnegative
from .experiment import ExperimentDefinition
from .graph import ConceptId, Graph


def run_directional(graph: Graph, route_weights: Mapping[tuple[ConceptId, ConceptId], float],
                    *, seeds: Mapping[ConceptId, float], decay: float,
                    max_steps: int, max_active: int) -> dict:
    """Читает Graph; возвращает полный trace с явным коэффициентом каждого прохода."""
    directions = {(source.id, target) for source in graph.concepts()
                  for target in graph.neighbors(source.id)}
    if set(route_weights) != directions:
        raise ValueError("Требуются ровно оба направления каждой существующей связи")
    weights = {pair: finite_nonnegative(value, "route_weight")
               for pair, value in route_weights.items()}
    # Публичный M2 используется только для валидации параметров и step 0.
    baseline = Activation(graph)
    baseline.start(seeds, decay=decay, max_steps=max_steps, max_active=max_active)
    snapshot = baseline.snapshot()
    active = {cid: snapshot["activation"][str(cid)] for cid in seeds
              if str(cid) in snapshot["activation"]}
    decay = snapshot["parameters"]["decay"]
    for step in range(1, max_steps + 1):
        sources, transitions = [], []
        candidates = {}
        for source in sorted(active):
            activation = active[source]
            sources.append(dict(id=str(source), activation=activation))
            for target in sorted(graph.neighbors(source)):
                strength = graph.get_connection(source, target).strength
                weight = weights[source, target]
                contribution = activation * strength * weight * decay
                total = candidates.get(target, 0.0) + contribution
                if not isfinite(contribution) or not isfinite(total):
                    raise ValueError("Переполнение activation в эксперименте M5.2")
                candidates[target] = total
                transitions.append(dict(source=str(source), target=str(target),
                                        source_activation=activation, strength=strength,
                                        route_weight=weight, decay=decay,
                                        contribution=contribution))
        ranked = sorted(candidates, key=lambda cid: (-candidates[cid], cid.int))
        kept = ranked[:max_active]
        active = {cid: candidates[cid] for cid in kept}
        snapshot["traces"].append(dict(
            step=step, sources=sources, transitions=transitions,
            candidates=[dict(id=str(cid), activation=candidates[cid], kept=cid in kept)
                        for cid in ranked],
            kept=[str(cid) for cid in kept], pruned=[str(cid) for cid in ranked[max_active:]]))
    snapshot.update(activation={str(cid): value for cid, value in active.items()},
                    step=max_steps, trace=snapshot["traces"][-1])
    return snapshot


def scenario_weights(graph: Graph, labels: Mapping[ConceptId, str]) -> dict:
    """Фиксированные коэффициенты M5.2 задаются отдельно от топологии M5.1."""
    ids = {label: cid for cid, label in labels.items()}
    asymmetric = {}
    for source, target in (("A", "C"), ("B", "D"), ("C", "X"),
                           ("D", "X"), ("C", "E"), ("D", "F")):
        asymmetric[ids[source], ids[target]] = 1.0
        asymmetric[ids[target], ids[source]] = 0.5
    symmetric = {(source.id, target): 1.0 for source in graph.concepts()
                 for target in graph.neighbors(source.id)}
    return {"symmetric_control": symmetric, "asymmetric_traversal": asymmetric}


def main() -> None:
    parser = argparse.ArgumentParser(description="Полные traces эксперимента M5.2")
    parser.add_argument("experiment", nargs="?",
                        default="experiments/m5-1-backwave-echo.neuroliq.json",
                        help="Исходный файл M5.1")
    definition = ExperimentDefinition.load(parser.parse_args().experiment)
    graph, labels = definition.build()
    results = {name: run_directional(graph, weights, **definition.run.model_dump())
               for name, weights in scenario_weights(graph, labels).items()}
    print(json.dumps(dict(labels={str(cid): label for cid, label in labels.items()},
                         scenarios=results), ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
