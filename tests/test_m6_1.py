"""Целевые проверки временных достроек M6.1 и неизменности сохранённого."""

from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import pytest

from neuroliq.graph import Graph
from neuroliq.m6_0 import RouteBundle
from neuroliq.m6_1 import candidate_paths, complete, fixture, run_experiment


def expected_paths(ids):
    return [[str(ids[n]) for n in path] for path in
            [("WALK", "ROAD", "ASPHALT", "FALL"), ("WALK", "ICE", "SLIP", "FALL")]]


def test_search_and_saved_structure_remain_separate():
    graph, ids, bundle = fixture()
    result = run_experiment()
    assert result["candidate_paths"] == sorted(expected_paths(ids))
    assert bundle.routes == [["h1", "w1"], ["h1", "f1"]]
    assert bundle.occurrences == dict(h1=ids["HUMAN"], w1=ids["WALK"], f1=ids["FALL"])
    assert result["saved_projection"] == bundle.project(graph)
    assert len(graph.concepts()) == 9 and len(graph.connections()) == 10
    assert all(c.strength == 1.0 for c in graph.connections())
    assert result["candidate_kind"] == "runtime_candidate"
    assert result["saved_before"] == result["saved_after"] == bundle.model_dump(mode="json")
    assert result["saved_serialized_before"].encode() == result["saved_serialized_after"].encode()
    assert result["graph_before"] == result["graph_after"]
    for path in result["candidate_paths"]:
        assert set(path[1:-1]).isdisjoint(str(cid) for cid in bundle.occurrences.values())
    assert all(all(s["unchanged"].values()) for s in result["scenarios"].values())


@pytest.mark.parametrize("scenario,supports,internal", [
    ("baseline", (1.0, 1.0), (0.5, 0.5, 0.5, 0.5)),
    ("clue_ice", (1.0, 1.5), (0.5, 0.5, 1.0, 0.5)),
    ("clue_road", (1.5, 1.0), (1.0, 0.5, 0.5, 0.5)),
])
def test_exact_support_ranking_and_full_trace(scenario, supports, internal):
    graph, ids, bundle = fixture()
    result = run_experiment()["scenarios"][scenario]
    paths = expected_paths(ids)
    rows = {tuple(row["path"]): row for row in result["ranking"]}
    assert tuple(rows[tuple(p)]["candidate_support"] for p in paths) == supports
    actual = {cid: value for row in rows.values() for cid, value in row["internal_activation"].items()}
    assert actual == {str(ids[n]): v for n, v in
                      zip(("ROAD", "ASPHALT", "ICE", "SLIP"), internal)}
    expected_seeds = {str(cid): 1.0 for cid in bundle.occurrences.values()}
    if scenario != "baseline":
        expected_seeds[str(ids[scenario.upper()])] = 1.0
    assert result["seeds"] == expected_seeds
    snapshot = result["activation"]
    assert snapshot["step"] == 1 and len(snapshot["traces"]) == 2
    assert snapshot["parameters"] == dict(decay=0.5, max_steps=1, max_active=9)
    assert not any(t["pruned"] for t in snapshot["traces"])
    assert {c["id"]: c["activation"] for c in snapshot["traces"][0]["candidates"]} == expected_seeds
    trace = snapshot["trace"]
    assert {s["id"]: s["activation"] for s in trace["sources"]} == expected_seeds
    expected_edges = {(source, str(target)) for source in expected_seeds
                      for target in graph.neighbors(UUID(source))}
    transitions = trace["transitions"]
    assert {(t["source"], t["target"]) for t in transitions} == expected_edges
    assert len(transitions) == len(expected_edges)
    totals = defaultdict(float)
    for t in transitions:
        assert t["source_activation"] == t["strength"] == 1.0
        assert t["decay"] == t["contribution"] == 0.5
        totals[t["target"]] += t["contribution"]
    assert snapshot["activation"] == dict(totals)
    assert {c["id"]: c["activation"] for c in trace["candidates"]} == dict(totals)
    leaders = paths if scenario == "baseline" else [paths[supports.index(max(supports))]]
    assert result["leaders"] == sorted(leaders)
    assert result["unique_leader"] == (scenario != "baseline")
    assert [row["candidate_support"] for row in result["ranking"]] == sorted(supports, reverse=True)


def test_generic_ids_without_labels_and_unchanged_objects():
    original, ids, saved = fixture()
    graph = Graph()
    remap = {c.id: graph.create_concept(uuid4()).id for c in reversed(original.concepts())}
    for c in reversed(original.connections()):
        graph.create_connection(remap[c.concept_b], remap[c.concept_a], c.strength)
    bundle = RouteBundle(occurrences={f"другое-{oid}": remap[cid]
                                     for oid, cid in reversed(list(saved.occurrences.items()))},
                         routes=[[f"другое-{oid}" for oid in r] for r in reversed(saved.routes)])
    before = (graph.concepts(), graph.connections(), bundle.model_dump_json(),
              tuple(graph.neighbors(c.id) for c in graph.concepts()))
    result = complete(graph, bundle, remap[ids["WALK"]], remap[ids["FALL"]],
                      dict(a=None, b=remap[ids["CLUE_ICE"]], c=remap[ids["CLUE_ROAD"]]))
    inverse = {str(new): str(old) for old, new in remap.items()}
    reference = run_experiment()
    for name, scenario in zip(("a", "b", "c"), reference["scenarios"].values()):
        actual = result["scenarios"][name]
        def scores(rows, translate):
            return {tuple(translate(cid) for cid in row["path"]): row["candidate_support"]
                    for row in rows}
        assert scores(actual["ranking"], inverse.__getitem__) == scores(scenario["ranking"], str)
        assert actual["unique_leader"] == scenario["unique_leader"]
        assert {tuple(inverse[cid] for cid in p) for p in actual["leaders"]} == {
            tuple(p) for p in scenario["leaders"]}
    assert before == (graph.concepts(), graph.connections(), bundle.model_dump_json(),
                      tuple(graph.neighbors(c.id) for c in graph.concepts()))
    assert all(graph.get_concept(c.id) is c for c in before[0])
    assert all(graph.get_connection(c.concept_b, c.concept_a) is c for c in before[1])


def test_search_bounds_exclusion_and_no_cycles():
    graph, ids, bundle = fixture()
    args = (graph, ids["WALK"], ids["FALL"], set(bundle.occurrences.values()))
    assert candidate_paths(*args, max_edges=2, max_expansions=100) == ()
    for bound in (3, 8):
        paths = candidate_paths(*args, max_edges=bound, max_expansions=100)
        assert {tuple(str(cid) for cid in p) for p in paths} == {tuple(p) for p in expected_paths(ids)}
        assert all(len(p) == len(set(p)) for p in paths)
    unrestricted = candidate_paths(graph, ids["WALK"], ids["FALL"], set(),
                                    max_edges=3, max_expansions=100)
    assert (ids["WALK"], ids["HUMAN"], ids["FALL"]) in unrestricted
    with pytest.raises(ValueError, match="Исчерпан"):
        candidate_paths(*args, max_edges=3, max_expansions=1)


def test_cli_full_diagnostics():
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(subprocess.check_output([sys.executable, "-m", "neuroliq.m6_1"], cwd=root))
    assert payload == run_experiment()
