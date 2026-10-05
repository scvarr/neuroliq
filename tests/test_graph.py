from dataclasses import FrozenInstanceError, fields
from uuid import UUID

import pytest

from neuroliq import Concept, Connection, Graph
from neuroliq.diagnostics import diagnostic_snapshot
from neuroliq.fixture import build_fixture


def test_concept_ids_are_unique_and_explicit_duplicates_are_rejected():
    graph = Graph()
    concepts = [graph.create_concept() for _ in range(1000)]
    assert len({concept.id for concept in concepts}) == 1000
    other = Graph().create_concept()
    assert other.id not in {concept.id for concept in concepts}
    assert graph.get_concept(concepts[0].id) == concepts[0]
    with pytest.raises(ValueError):
        graph.create_concept(concepts[0].id)
    assert graph.concepts() == tuple(concepts)


def test_core_records_are_minimal_and_immutable():
    assert [field.name for field in fields(Concept)] == ["id"]
    assert [field.name for field in fields(Connection)] == [
        "concept_a", "concept_b", "strength"
    ]
    graph, _ = build_fixture()
    with pytest.raises(FrozenInstanceError):
        graph.concepts()[0].id = UUID(int=99)
    with pytest.raises(FrozenInstanceError):
        graph.connections()[0].strength = 99.0
    with pytest.raises(TypeError):
        graph.create_concept("человеческая метка")


def test_connection_lookup_and_neighbors_are_symmetric():
    graph = Graph()
    a, b, isolated = [graph.create_concept().id for _ in range(3)]
    edge = graph.create_connection(b, a, -12.5)
    assert graph.get_connection(a, b) == edge
    assert graph.get_connection(b, a) == edge
    assert graph.neighbors(a) == (b,)
    assert graph.neighbors(b) == (a,)
    assert graph.neighbors(isolated) == ()
    assert graph.connections() == (edge,)
    assert graph.get_connection(a, isolated) is None
    assert graph.get_connection(a, a) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_connection_does_not_replace_strength(reverse):
    graph = Graph()
    a, b = [graph.create_concept().id for _ in range(2)]
    edge = graph.create_connection(a, b, 1.5)
    ends = (b, a) if reverse else (a, b)
    with pytest.raises(ValueError):
        graph.create_connection(*ends, 9.0)
    assert graph.connections() == (edge,)
    assert graph.neighbors(a) == (b,)
    assert graph.neighbors(b) == (a,)


def test_self_loop_is_rejected_without_mutation():
    graph = Graph()
    concept = graph.create_concept()
    with pytest.raises(ValueError):
        graph.create_connection(concept.id, concept.id, 1.0)
    assert graph.connections() == ()
    assert graph.neighbors(concept.id) == ()


@pytest.mark.parametrize("strength", [float("nan"), float("inf"), -float("inf"), 10**400])
def test_non_finite_strength_is_rejected_without_mutation(strength):
    graph = Graph()
    a, b = [graph.create_concept().id for _ in range(2)]
    with pytest.raises(ValueError):
        graph.create_connection(a, b, strength)
    assert graph.connections() == ()
    assert graph.neighbors(a) == graph.neighbors(b) == ()


@pytest.mark.parametrize("strength", [-1e300, 0, 1e300])
def test_finite_strength_has_no_prescribed_range(strength):
    graph = Graph()
    a, b = [graph.create_concept().id for _ in range(2)]
    assert graph.create_connection(a, b, strength).strength == strength


@pytest.mark.parametrize("strength", [True, "1.5", None])
def test_non_numeric_strength_is_rejected(strength):
    graph = Graph()
    a, b = [graph.create_concept().id for _ in range(2)]
    with pytest.raises(TypeError):
        graph.create_connection(a, b, strength)
    assert graph.connections() == ()


def test_unknown_concepts_and_empty_graph():
    graph = Graph()
    missing = UUID(int=99)
    assert graph.concepts() == graph.connections() == ()
    assert graph.get_concept(missing) is None
    assert graph.get_connection(missing, UUID(int=98)) is None
    with pytest.raises(KeyError):
        graph.neighbors(missing)
    a = graph.create_concept().id
    for ends in ((a, missing), (missing, a)):
        with pytest.raises(KeyError):
            graph.create_connection(*ends, 1.0)
    assert graph.connections() == ()
    assert graph.neighbors(a) == ()


def test_read_collections_are_independent_snapshots():
    graph = Graph()
    first = graph.create_concept()
    concepts, connections, neighbors = graph.concepts(), graph.connections(), graph.neighbors(first.id)
    second = graph.create_concept()
    graph.create_connection(first.id, second.id, 1)
    assert concepts == (first,)
    assert connections == neighbors == ()


def test_fixture_snapshot_is_exact_and_reproducible():
    graph, labels = build_fixture()
    prefix = "00000000-0000-0000-0000-00000000000"
    expected = f'''Концепты (5):
  {prefix}1 "Альфа"
  {prefix}2 "Бета"
  {prefix}3 "Гамма"
  {prefix}4 "Дельта"
  {prefix}5 "Изолированный"
Связи (4, неориентированные):
  {prefix}1 -- {prefix}2: 1.5
  {prefix}1 -- {prefix}3: -2.0
  {prefix}2 -- {prefix}3: 0.0
  {prefix}3 -- {prefix}4: 12.25'''
    assert diagnostic_snapshot(graph, labels) == expected
    assert diagnostic_snapshot(*build_fixture()) == expected
    reordered = Graph()
    for concept in reversed(graph.concepts()):
        reordered.create_concept(concept.id)
    for edge in reversed(graph.connections()):
        reordered.create_connection(edge.concept_b, edge.concept_a, edge.strength)
    assert diagnostic_snapshot(reordered, dict(reversed(list(labels.items())))) == expected
    assert graph.neighbors(UUID(int=5)) == ()
    assert diagnostic_snapshot(graph) == diagnostic_snapshot(graph, {})


def test_diagnostic_labels_are_external_and_escaped():
    graph = Graph()
    concept = graph.create_concept(UUID(int=1))
    before = graph.concepts()
    snapshot = diagnostic_snapshot(graph, {concept.id: 'Метка\n"внешняя"'})
    assert '"Метка\\n\\"внешняя\\""' in snapshot
    assert len(snapshot.splitlines()) == 3
    assert graph.concepts() == before
