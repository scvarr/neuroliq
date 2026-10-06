"""M6.1: временные кандидатные достройки, не сохраняемые как знание."""

from collections.abc import Mapping
import json
from uuid import UUID

from .activation import Activation
from .graph import ConceptId, Graph
from .m6_0 import RouteBundle


def candidate_paths(graph: Graph, source: ConceptId, target: ConceptId,
                    explicit: set[ConceptId], *, max_edges: int,
                    max_expansions: int) -> tuple[tuple[ConceptId, ...], ...]:
    """Ограниченный DFS простых путей; explicit запрещены внутри пути.

    При исчерпании бюджета поиска ошибка вместо неполного набора кандидатов.
    Порядок UUID нужен только для воспроизводимого перечисления.
    """
    if type(max_edges) is not int or max_edges < 1:
        raise ValueError("max_edges должен быть целым >= 1")
    if type(max_expansions) is not int or max_expansions < 1:
        raise ValueError("max_expansions должен быть целым >= 1")
    if any(graph.get_concept(cid) is None for cid in explicit | {source, target}):
        raise ValueError("Адрес поиска отсутствует в L0")
    if source == target:
        raise ValueError("Требуются разные концы кандидатного пути")
    pending = [(source,)]
    found = []
    expansions = 0
    while pending:
        path = pending.pop()
        expansions += 1
        if expansions > max_expansions:
            raise ValueError("Исчерпан max_expansions; поиск не завершён")
        if path[-1] == target:
            found.append(path)
            continue
        if len(path) - 1 == max_edges:
            continue
        for neighbor in sorted(graph.neighbors(path[-1]), reverse=True):
            if neighbor not in path and (neighbor == target or neighbor not in explicit):
                pending.append((*path, neighbor))
    return tuple(sorted(found))


def graph_snapshot(graph: Graph) -> dict:
    """Полное состояние публичной структуры, включая порядок и соседство."""
    return dict(
        concepts=[str(c.id) for c in graph.concepts()],
        connections=[dict(a=str(c.concept_a), b=str(c.concept_b), strength=c.strength)
                     for c in graph.connections()],
        neighbors={str(c.id): [str(cid) for cid in graph.neighbors(c.id)]
                   for c in graph.concepts()},
    )


def complete(graph: Graph, bundle: RouteBundle, source: ConceptId, target: ConceptId,
             clarifications: Mapping[str, ConceptId | None], *, max_edges: int = 3,
             max_expansions: int = 100) -> dict:
    """Независимые запуски M2 на одной структуре; labels не принимаются."""
    before = graph_snapshot(graph)
    saved_before = bundle.model_dump_json()
    saved_structure = bundle.model_dump(mode="json")
    projection = bundle.project(graph)
    explicit = set(bundle.occurrences.values())
    if source not in explicit or target not in explicit:
        raise ValueError("Концы достройки должны быть явно сохранёнными концептами")
    paths = candidate_paths(graph, source, target, explicit,
                            max_edges=max_edges, max_expansions=max_expansions)
    scenarios = {}
    for name, clue in clarifications.items():
        seeds = {cid: 1.0 for cid in explicit}
        if clue is not None:
            seeds[clue] = 1.0
        activation = Activation(graph)
        activation.start(seeds, decay=0.5, max_steps=1, max_active=len(graph.concepts()))
        activation.step()
        snapshot = activation.snapshot()
        ranking = []
        for path in paths:
            internal = {str(cid): snapshot["activation"].get(str(cid), 0.0)
                        for cid in path[1:-1]}
            ranking.append(dict(path=[str(cid) for cid in path],
                                internal_activation=internal,
                                candidate_support=sum(internal.values())))
        ranking.sort(key=lambda item: (-item["candidate_support"], item["path"]))
        leaders = [item["path"] for item in ranking
                   if item["candidate_support"] == ranking[0]["candidate_support"]]
        unchanged = dict(graph=before == graph_snapshot(graph),
                         saved_bytes=saved_before.encode("utf-8") ==
                         bundle.model_dump_json().encode("utf-8"),
                         saved_structure=saved_structure == bundle.model_dump(mode="json"))
        if not all(unchanged.values()):
            raise AssertionError("Постоянная структура изменена")
        scenarios[name] = dict(seeds={str(cid): seeds[cid] for cid in sorted(seeds)},
                               activation=snapshot, ranking=ranking, leaders=leaders,
                               unique_leader=len(leaders) == 1, unchanged=unchanged)
    return dict(saved_before=saved_structure, saved_projection=projection,
                saved_serialized_before=saved_before,
                search=dict(source=str(source), target=str(target), max_edges=max_edges,
                            max_expansions=max_expansions,
                            excluded_internal=sorted(str(cid) for cid in explicit)),
                candidate_paths=[[str(cid) for cid in path] for path in paths],
                candidate_kind="runtime_candidate", scenarios=scenarios,
                graph_before=before, graph_after=graph_snapshot(graph),
                saved_after=bundle.model_dump(mode="json"),
                saved_serialized_after=bundle.model_dump_json())


def fixture() -> tuple[Graph, dict[str, ConceptId], RouteBundle]:
    """Искусственный симметричный L0; имена используются только при сборке."""
    graph = Graph()
    names = ("HUMAN", "WALK", "FALL", "ROAD", "ASPHALT", "ICE", "SLIP",
             "CLUE_ROAD", "CLUE_ICE")
    ids = {name: graph.create_concept(UUID(int=601 + i)).id for i, name in enumerate(names)}
    for a, b in (("WALK", "ROAD"), ("ROAD", "ASPHALT"), ("ASPHALT", "FALL"),
                 ("WALK", "ICE"), ("ICE", "SLIP"), ("SLIP", "FALL"),
                 ("HUMAN", "WALK"), ("HUMAN", "FALL"),
                 ("CLUE_ROAD", "ROAD"), ("CLUE_ICE", "ICE")):
        graph.create_connection(ids[a], ids[b], 1.0)
    bundle = RouteBundle(occurrences=dict(h1=ids["HUMAN"], w1=ids["WALK"], f1=ids["FALL"]),
                         routes=[["h1", "w1"], ["h1", "f1"]])
    return graph, ids, bundle


def run_experiment() -> dict:
    graph, ids, bundle = fixture()
    result = complete(graph, bundle, ids["WALK"], ids["FALL"],
                      dict(baseline=None, clue_ice=ids["CLUE_ICE"], clue_road=ids["CLUE_ROAD"]))
    result["labels"] = {str(cid): name for name, cid in ids.items()}
    return result


if __name__ == "__main__":
    print(json.dumps(run_experiment(), ensure_ascii=False, indent=2))
