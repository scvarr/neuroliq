"""Контракт M6.0: проекция, тождество вхождений и структурный round-trip."""

import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest

from neuroliq.graph import Graph
from neuroliq.m6_0 import RouteBundle, controls, round_trip, run_experiment


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["two_human", "shared_anchor"])
def test_controls_and_round_trip(name):
    graph, ids, pairs = controls()
    a, b = pairs[name]
    expected = ([[str(ids[n]) for n in ("HUMAN", "HIT", "HUMAN")]]
                if name == "two_human" else sorted([
                    [str(ids[n]) for n in route]
                    for route in [("TALL", "HUMAN"), ("HUMAN", "PLAY", "BASKETBALL"),
                                  ("WELL", "PLAY")]]))
    assert a.project(graph) == b.project(graph) == expected
    assert a.canonical() != b.canonical()
    for bundle in (a, b):
        result = round_trip(bundle, graph)
        restored = RouteBundle.model_validate_json(result["serialized"])
        assert result["round_trip_equal"] and result["projection_preserved"]
        assert restored.occurrences == bundle.occurrences
        assert restored.routes == bundle.routes
        assert result["restored_canonical"] == bundle.canonical()
    restored_a = RouteBundle.model_validate_json(round_trip(a, graph)["serialized"])
    if name == "two_human":
        assert restored_a.routes[0][0] != restored_a.routes[0][-1]
        restored_b = RouteBundle.model_validate_json(round_trip(b, graph)["serialized"])
        assert restored_b.routes[0][0] == restored_b.routes[0][-1]
        assert a.canonical()["routes"] == [["o0", "o1", "o2"]]
        assert b.canonical()["routes"] == [["o0", "o1", "o0"]]
    else:
        assert restored_a.routes[0][-1] == restored_a.routes[1][0]
        assert restored_a.routes[1][1] == restored_a.routes[2][-1]
        restored_b = RouteBundle.model_validate_json(round_trip(b, graph)["serialized"])
        assert restored_b.routes[0][-1] != restored_b.routes[1][0]
        assert restored_b.routes[1][1] == restored_b.routes[2][-1]


def test_canonical_ignores_names_mapping_order_and_bundle_order():
    graph, _, pairs = controls()
    for pair in pairs.values():
        for bundle in pair:
            rename = {oid: f"другое-{i}" for i, oid in enumerate(reversed(bundle.occurrences))}
            renamed = RouteBundle(
                occurrences={rename[oid]: cid for oid, cid in reversed(list(bundle.occurrences.items()))},
                routes=[[rename[oid] for oid in route] for route in reversed(bundle.routes)])
            assert renamed.canonical() == bundle.canonical()
            assert round_trip(renamed, graph)["restored_canonical"] == bundle.canonical()


def test_order_and_route_multiplicity_remain_significant():
    _, _, pairs = controls()
    original = pairs["shared_anchor"][0]
    reversed_route = RouteBundle(occurrences=original.occurrences,
                                 routes=[original.routes[0][::-1], *original.routes[1:]])
    duplicate = RouteBundle(occurrences=original.occurrences,
                            routes=[*original.routes, original.routes[0]])
    assert original.canonical() != reversed_route.canonical()
    assert original.canonical() != duplicate.canonical()


def test_generic_concepts_and_unchanged_public_graph():
    _, _, pairs = controls()
    graph = Graph()
    all_ids = {cid for pair in pairs.values() for bundle in pair for cid in bundle.occurrences.values()}
    remap = {cid: graph.create_concept(UUID(int=800 - i)).id
             for i, cid in enumerate(sorted(all_ids))}
    for pair in pairs.values():
        for bundle in pair:
            projected = [[remap[bundle.occurrences[oid]] for oid in route] for route in bundle.routes]
            for route in projected:
                for a, b in zip(route, route[1:]):
                    if graph.get_connection(a, b) is None:
                        graph.create_connection(a, b, 1.0)
    before = (graph.concepts(), graph.connections(),
              tuple(graph.neighbors(c.id) for c in graph.concepts()))
    for pair in pairs.values():
        converted = [RouteBundle(occurrences={oid: remap[cid] for oid, cid in bundle.occurrences.items()},
                                 routes=bundle.routes) for bundle in pair]
        assert converted[0].project(graph) == converted[1].project(graph)
        assert converted[0].canonical() != converted[1].canonical()
        assert all(round_trip(bundle, graph)["round_trip_equal"] for bundle in converted)
    assert before == (graph.concepts(), graph.connections(),
                      tuple(graph.neighbors(c.id) for c in graph.concepts()))
    assert all(graph.get_connection(c.concept_b, c.concept_a) is c for c in before[1])


@pytest.mark.parametrize("kind", ["missing_connection", "missing_concept", "self_loop"])
def test_invalid_l0_projection_rejected(kind):
    graph, ids, _ = controls()
    a, b = {"missing_connection": (ids["TALL"], ids["BASKETBALL"]),
            "missing_concept": (ids["HUMAN"], UUID(int=999)),
            "self_loop": (ids["HUMAN"], ids["HUMAN"])}[kind]
    bundle = RouteBundle(occurrences=dict(a=a, b=b), routes=[["a", "b"]])
    with pytest.raises(ValueError, match="отсутствует"):
        round_trip(bundle, graph)


@pytest.mark.parametrize("routes", [[], [[]], [["missing"]]])
def test_invalid_structure_rejected(routes):
    with pytest.raises(ValueError):
        RouteBundle(occurrences={"a": UUID(int=501)}, routes=routes)


def test_cli_diagnostics_reproducible():
    payload = json.loads(subprocess.check_output([sys.executable, "-m", "neuroliq.m6_0"], cwd=ROOT))
    assert payload == run_experiment()
    assert payload == json.loads((ROOT / "experiments/m6-0-structural-round-trip.json").read_bytes())
    assert payload["missing_connection"]["rejected"]
    assert all(pair["same_projection"] and pair["different_structure"]
               for pair in payload["pairs"].values())
