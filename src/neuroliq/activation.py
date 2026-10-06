"""Временная наблюдаемая волна M2; постоянный граф только читается."""

from collections.abc import Mapping
from copy import deepcopy
from math import isfinite

from .graph import ConceptId, Graph


def finite_nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: требуется конечное неотрицательное число")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{name}: число слишком велико") from error
    if not isfinite(number) or number < 0:
        raise ValueError(f"{name}: требуется конечное неотрицательное число")
    return number


class Activation:
    """Один запуск. Порядок переходов и tie-break определяются ConceptId."""

    def __init__(self, graph: Graph):
        self.graph = graph
        self.reset()

    def reset(self) -> None:
        self._active: dict[ConceptId, float] = {}
        self._traces: list[dict] = []
        self._parameters: dict | None = None

    def start(self, seeds: Mapping[ConceptId, float], *, decay: float,
              max_steps: int, max_active: int) -> None:
        decay = finite_nonnegative(decay, "decay")
        if decay > 1:
            raise ValueError("decay должен быть от 0 до 1")
        for name, value, minimum in (("max_steps", max_steps, 0), ("max_active", max_active, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name}: требуется целое число >= {minimum}")
        if not seeds:
            raise ValueError("Требуется хотя бы один seed")
        candidates = {}
        for concept_id, value in seeds.items():
            if self.graph.get_concept(concept_id) is None:
                raise ValueError(f"Неизвестный seed: {concept_id}")
            candidates[concept_id] = finite_nonnegative(value, "activation")
        if any(c.strength < 0 for c in self.graph.connections()):
            raise ValueError("M2 не поддерживает отрицательные strength")
        self.reset()
        self._parameters = dict(decay=decay, max_steps=max_steps, max_active=max_active)
        self._record(candidates, [], [])

    def _record(self, candidates: dict, sources: list, transitions: list) -> None:
        ranked = sorted(candidates, key=lambda cid: (-candidates[cid], cid.int))
        kept = ranked[:self._parameters["max_active"]]
        trace = {
            "step": len(self._traces), "sources": sources, "transitions": transitions,
            "candidates": [{"id": str(cid), "activation": candidates[cid],
                            "kept": cid in kept} for cid in ranked],
            "kept": [str(cid) for cid in kept],
            "pruned": [str(cid) for cid in ranked[len(kept):]],
        }
        self._active = {cid: candidates[cid] for cid in kept}
        self._traces.append(trace)

    def step(self) -> None:
        if self._parameters is None:
            raise ValueError("Сначала задайте seeds и параметры запуска")
        if len(self._traces) - 1 >= self._parameters["max_steps"]:
            return
        candidates: dict[ConceptId, float] = {}
        sources, transitions = [], []
        decay = self._parameters["decay"]
        for source in sorted(self._active):
            activation = self._active[source]
            sources.append({"id": str(source), "activation": activation})
            for target in sorted(self.graph.neighbors(source)):
                strength = self.graph.get_connection(source, target).strength
                contribution = activation * strength * decay
                total = candidates.get(target, 0.0) + contribution
                if not isfinite(contribution) or not isfinite(total):
                    raise ValueError("Переполнение activation; состояние шага не изменено")
                candidates[target] = total
                transitions.append(dict(source=str(source), target=str(target),
                                        source_activation=activation, strength=strength,
                                        decay=decay, contribution=contribution))
        self._record(candidates, sources, transitions)

    def run(self) -> None:
        if self._parameters is None:
            raise ValueError("Сначала задайте seeds и параметры запуска")
        while len(self._traces) - 1 < self._parameters["max_steps"]:
            self.step()

    def snapshot(self) -> dict:
        return deepcopy({"activation": {str(cid): value for cid, value in self._active.items()},
                         "parameters": self._parameters, "step": len(self._traces) - 1,
                         "trace": self._traces[-1] if self._traces else None,
                         "traces": self._traces})
