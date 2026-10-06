"""Ограниченный пакетный эксперимент M5.3 с краткоживущей деформацией."""

import argparse
import json
from math import isfinite

from .activation import Activation
from .experiment import ExperimentDefinition
from .graph import ConceptId, Graph


H = 0.5
RHO = 0.5


def run_transient(graph: Graph, *, seeds: dict[ConceptId, float], decay: float,
                  max_steps: int, max_active: int, dynamic: bool) -> dict:
    """Один источник и один выбранный переход; trace не участвует в выборе."""
    if len(seeds) != 1 or max_active != 1:
        raise ValueError("M5.3 требует один seed и max_active=1")
    if type(dynamic) is not bool:
        raise ValueError("dynamic должен быть bool")
    baseline = Activation(graph)
    baseline.start(seeds, decay=decay, max_steps=max_steps, max_active=max_active)
    snapshot = baseline.snapshot()
    active = {cid: snapshot["activation"][str(cid)] for cid in seeds}
    decay = snapshot["parameters"]["decay"]
    refractory = {(source.id, target): 0.0 for source in graph.concepts()
                  for target in graph.neighbors(source.id)}

    def state() -> list[dict]:
        return [dict(source=str(s), target=str(t), r=refractory[s, t])
                for s, t in sorted(refractory)]

    snapshot["parameters"].update(dynamic=dynamic, h=H, rho=RHO)
    snapshot["traces"][0]["transient_after_update"] = state()
    for step in range(1, max_steps + 1):
        sources, transitions, candidates = [], [], {}
        for source, activation in active.items():
            sources.append(dict(id=str(source), activation=activation))
            for target in sorted(graph.neighbors(source)):
                strength = graph.get_connection(source, target).strength
                r = refractory[source, target]
                weight = 1.0 - r
                contribution = activation * strength * weight * decay
                if not isfinite(contribution):
                    raise ValueError("Переполнение activation в эксперименте M5.3")
                candidates[target] = contribution
                transitions.append(dict(source=str(source), target=str(target),
                                        source_activation=activation, strength=strength,
                                        r=r, route_weight=weight, decay=decay,
                                        contribution=contribution))
        ranked = sorted(candidates, key=lambda cid: (-candidates[cid], cid.int))
        kept = ranked[:1]
        for transition in transitions:
            transition["kept"] = transition["target"] in [str(cid) for cid in kept]
        # Только фактический выбор запускает update; candidates состояние не меняют.
        if dynamic and kept:
            refractory = {pair: RHO * value for pair, value in refractory.items()}
            source = next(iter(active))
            refractory[kept[0], source] = H
        active = {cid: candidates[cid] for cid in kept}
        snapshot["traces"].append(dict(
            step=step, sources=sources, transitions=transitions,
            candidates=[dict(id=str(cid), activation=candidates[cid], kept=cid in kept)
                        for cid in ranked],
            kept=[str(cid) for cid in kept], pruned=[str(cid) for cid in ranked[1:]],
            transient_after_update=state()))
    snapshot.update(activation={str(cid): value for cid, value in active.items()},
                    step=max_steps, trace=snapshot["traces"][-1])
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Полные control/dynamic traces M5.3")
    parser.add_argument("experiment", nargs="?",
                        default="experiments/m5-3-transient-direction-state.neuroliq.json",
                        help="Исходная минимальная топология M5.3")
    definition = ExperimentDefinition.load(parser.parse_args().experiment)
    graph, labels = definition.build()
    results = {name: run_transient(graph, dynamic=dynamic, **definition.run.model_dump())
               for name, dynamic in (("control", False), ("dynamic", True))}
    print(json.dumps(dict(labels={str(cid): label for cid, label in labels.items()},
                         scenarios=results), ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
