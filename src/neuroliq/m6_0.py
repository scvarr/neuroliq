"""Изолированный M6.0: сохранение вхождений и общих якорей поверх L0."""

from itertools import permutations
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from .graph import ConceptId, Graph


class RouteBundle(BaseModel):
    """Только экспериментальная конструкция; порядок внутри Route значим."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    occurrences: dict[StrictStr, ConceptId]
    routes: list[list[StrictStr]]

    @model_validator(mode="after")
    def check_structure(self) -> "RouteBundle":
        if not self.routes or any(not route for route in self.routes):
            raise ValueError("Bundle и каждый Route должны быть непустыми")
        if any(not oid for oid in self.occurrences):
            raise ValueError("OccurrenceId должен быть непустым")
        used = {oid for route in self.routes for oid in route}
        if used != set(self.occurrences):
            raise ValueError("Каждое вхождение должно быть определено и использовано")
        return self

    def project(self, graph: Graph) -> list[list[str]]:
        """Проверить адреса и существующие Connection, не изменяя L0."""
        for oid, cid in self.occurrences.items():
            if graph.get_concept(cid) is None:
                raise ValueError(f"Концепт вхождения {oid} отсутствует в L0: {cid}")
        projected = []
        for index, route in enumerate(self.routes):
            concepts = [self.occurrences[oid] for oid in route]
            for source, target in zip(concepts, concepts[1:]):
                if graph.get_connection(source, target) is None:
                    raise ValueError(
                        f"Route {index}: отсутствует Connection L0 {source} — {target}"
                    )
            projected.append([str(cid) for cid in concepts])
        return sorted(projected)

    def canonical(self) -> dict:
        """Переименовать по первому появлению; bundle — мультимножество Route.

        Перебор порядка Route даёт независимость от их перечисления и имён
        вхождений. Факториальная процедура предназначена только для малых
        ручных конструкций M6.0, а не для production или масштабирования.
        """
        candidates = []
        for routes in permutations(self.routes):
            names: dict[str, int] = {}
            concepts = []
            normalized = []
            for route in routes:
                path = []
                for oid in route:
                    if oid not in names:
                        names[oid] = len(names)
                        concepts.append(str(self.occurrences[oid]))
                    path.append(names[oid])
                normalized.append(tuple(path))
            candidates.append((tuple(concepts), tuple(normalized)))
        concepts, routes = min(candidates)
        return dict(occurrences={f"o{i}": cid for i, cid in enumerate(concepts)},
                    routes=[[f"o{i}" for i in route] for route in routes])


def round_trip(bundle: RouteBundle, graph: Graph) -> dict:
    """Валидация → проекция → JSON → чтение → каноническая структура."""
    projection = bundle.project(graph)
    serialized = bundle.model_dump_json(indent=2)
    restored = RouteBundle.model_validate_json(serialized)
    restored_projection = restored.project(graph)
    original = bundle.canonical()
    canonical = restored.canonical()
    return dict(original=bundle.model_dump(mode="json"), projection=projection,
                serialized=serialized, restored_canonical=canonical,
                original_canonical=original,
                round_trip_equal=original == canonical,
                projection_preserved=projection == restored_projection)


def controls() -> tuple[Graph, dict[str, ConceptId], dict[str, tuple[RouteBundle, RouteBundle]]]:
    """Ручные controls; labels используются только при сборке и диагностике."""
    graph = Graph()
    ids = {name: graph.create_concept(UUID(int=501 + i)).id
           for i, name in enumerate(("HUMAN", "HIT", "TALL", "PLAY", "BASKETBALL", "WELL"))}
    for a, b in (("HUMAN", "HIT"), ("TALL", "HUMAN"), ("HUMAN", "PLAY"),
                 ("PLAY", "BASKETBALL"), ("WELL", "PLAY")):
        graph.create_connection(ids[a], ids[b], 1.0)

    def bundle(occurrences, routes):
        return RouteBundle(occurrences={oid: ids[name] for oid, name in occurrences.items()},
                           routes=routes)

    human_a = bundle(dict(h1="HUMAN", hit1="HIT", h2="HUMAN"), [["h1", "hit1", "h2"]])
    human_b = bundle(dict(h1="HUMAN", hit1="HIT"), [["h1", "hit1", "h1"]])
    shared = dict(t1="TALL", h1="HUMAN", p1="PLAY", b1="BASKETBALL", w1="WELL")
    anchor_a = bundle(shared, [["t1", "h1"], ["h1", "p1", "b1"], ["w1", "p1"]])
    anchor_b = bundle({**shared, "h2": "HUMAN"},
                      [["t1", "h1"], ["h2", "p1", "b1"], ["w1", "p1"]])
    return graph, ids, dict(two_human=(human_a, human_b), shared_anchor=(anchor_a, anchor_b))


def run_experiment() -> dict:
    graph, ids, pairs = controls()
    results = {}
    for name, pair in pairs.items():
        a, b = [round_trip(bundle, graph) for bundle in pair]
        results[name] = dict(A=a, B=b, same_projection=a["projection"] == b["projection"],
                             different_structure=a["restored_canonical"] != b["restored_canonical"])
    invalid = RouteBundle(occurrences=dict(t=ids["TALL"], b=ids["BASKETBALL"]),
                          routes=[["t", "b"]])
    try:
        invalid.project(graph)
    except ValueError as error:
        rejection = str(error)
    else:
        raise AssertionError("Route с отсутствующей Connection принят")
    return dict(labels={str(cid): name for name, cid in ids.items()},
                connections=[dict(a=str(c.concept_a), b=str(c.concept_b), strength=c.strength)
                             for c in graph.connections()], pairs=results,
                missing_connection=dict(original=invalid.model_dump(mode="json"),
                                        rejected=True, reason=rejection))


if __name__ == "__main__":
    print(json.dumps(run_experiment(), ensure_ascii=False, indent=2))
