import json
import math
import subprocess
import sys
from uuid import UUID

import pytest

from neuroliq.m6_2 import RawTextBaseline, canonical_pair, tokenize
from neuroliq.m6_3 import StructuralAnalysis, cosine, jaccard, run_documents
from neuroliq.m6_3_dataset import validation_documents


def manual(keys=("a", "b", "x", "y", "z", "alone"), reverse_ids=False):
    baseline = RawTextBaseline(())
    for i, key in enumerate(keys, 1):
        baseline.token_ids[key] = baseline.graph.create_concept(
            UUID(int=100-i if reverse_ids else i)).id
        baseline.token_counts[key] = i
    for a, b, count in [(0, 2, 2), (0, 3, 1), (1, 2, 3), (1, 4, 4)]:
        baseline.graph.create_connection(baseline.token_ids[keys[a]],
                                         baseline.token_ids[keys[b]], 1.0)
        baseline.pair_counts[canonical_pair(keys[a], keys[b])] = count
    return baseline, StructuralAnalysis(baseline)


def test_manual_numeric_profiles():
    baseline, analysis = manual()
    a, b = (analysis.profiles[baseline.token_ids[k]] for k in ("a", "b"))
    assert a.frequency == 1
    assert a.degree == 2
    assert a.neighbors == frozenset(baseline.graph.neighbors(a.concept_id))
    assert jaccard(a, b) == pytest.approx(1/3)
    assert cosine(a, b) == pytest.approx(6 / math.sqrt(5*25))
    assert analysis.diagnose("a")["top_neighbors"][0] == {"token_key": "x", "pair_count": 2}


def test_zero_degree_and_overlap():
    _, analysis = manual()
    p = analysis.profiles
    a, x, alone = (p[analysis.token_ids[k]] for k in ("a", "x", "alone"))
    for measure in (jaccard, cosine):
        assert measure(a, x) == 0
        assert measure(a, alone) == 0
        assert measure(alone, alone) == 0


def test_query_exclusion_top_n_and_uuid_independent_ties():
    for reverse in (False, True):
        _, a = manual(reverse_ids=reverse)
        query = a.token_ids["alone"]
        for metric in ("jaccard", "cosine"):
            ranking = a.rank(query, metric)
            assert query not in [cid for cid, _ in ranking]
            assert [a.labels[cid] for cid, _ in ranking] == ["a", "b", "x", "y", "z"]
            assert a.rank(query, metric, 2) == ranking[:2]
            assert a.rank(query, metric, 0) == []
            assert a.rank(query, metric, 100) == ranking


def test_renamed_isomorphic_graph_has_identical_all_pair_scores():
    keys = ("студент", "люди", "а", "!", "работа", "пустой")
    b1, a1 = manual()
    b2, a2 = manual(keys, True)
    for measure in (jaccard, cosine):
        for i, k1 in enumerate(b1.token_ids):
            for j, k2 in enumerate(b1.token_ids):
                assert measure(a1.profiles[b1.token_ids[k1]], a1.profiles[b1.token_ids[k2]]) == measure(
                    a2.profiles[b2.token_ids[keys[i]]], a2.profiles[b2.token_ids[keys[j]]])


def test_snapshots_limit_boundaries_and_m6_2_parity():
    documents = ["É E\u0301 Straße STRASSE .", "студент студенты студентов студент !"]
    queries = {"студент": ["студенты", "нет"]}
    reports = list(run_documents(documents, queries, checkpoints=(3, 7, 9), limit=9))
    assert [r["processed_token_occurrences"] for r in reports] == [3, 7, 9]
    assert reports[0]["queries"][0]["present"] is False
    assert reports[1]["queries"][0]["frequency"] == 1
    assert reports[2]["queries"][0]["frequency"] == 2
    baseline = RawTextBaseline((3, 7, 9))
    for doc in documents:
        for snapshot in baseline.ingest_document(doc):
            index = (3, 7, 9).index(snapshot["processed_token_occurrences"])
            assert reports[index]["graph_concepts"] == snapshot["graph_concepts"]
            assert reports[index]["graph_connections"] == snapshot["unique_graph_connections"]
    assert all(c.strength == 1 for c in baseline.graph.connections())
    assert list(tokenize(documents[0])) == ["é", "é", "strasse", "strasse", "."]
    assert reports[2]["self_pair_occurrences"] == 2
    assert reports[1]["queries"][0]["frequency"] == 1  # Снимок не мутировал.


def test_no_extra_documents_read_at_limit_and_no_cross_document_pair():
    def documents():
        yield "a a b c"
        raise AssertionError("Источник прочитан после лимита")
    reports = list(run_documents(documents(), {"a": []}, checkpoints=(2,), limit=2))
    assert reports[0]["graph_connections"] == 0
    assert reports[0]["self_pair_occurrences"] == 1
    final = list(run_documents(["a", "b"], {"a": []}, checkpoints=(3,), limit=3))[-1]
    assert final["kind"] == "final"
    assert final["graph_connections"] == 0
    assert final["queries"][0]["degree"] == 0
    assert list(run_documents([], {}, checkpoints=(), limit=1))[0]["graph_concepts"] == 0


def test_controls_missing_and_score():
    _, a = manual()
    report = a.diagnose("a", controls=["a", "b", "missing"], top_n=1)
    assert len(report["jaccard"]["top"]) == 1
    assert report["cosine"]["controls"][0]["score"] == pytest.approx(6/math.sqrt(125))
    assert report["jaccard"]["controls"][1] == {
        "token_key": "missing", "present": False, "rank": None, "score": None}


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": True},
    {"checkpoints": (2, 1)}, {"checkpoints": (1, 1)}, {"top_n": -1},
    {"limit": 1, "checkpoints": (2,)}])
def test_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        list(run_documents([], {}, **kwargs))


def test_dataset_adapter_fake_iterable_only_text():
    rows = [{"text": "А б", "annotation": object()}, {"text": ""}, {"text": "В"}]
    assert list(validation_documents(iter(rows))) == ["А б", "", "В"]
    with pytest.raises(ValueError):
        list(validation_documents([{"text": None}]))
    with pytest.raises(KeyError):
        list(validation_documents([{"other": "текст"}]))


def test_adapter_source_and_limit_snapshot():
    rows = [{"text": "a x", "annotation": "не используется"}, {"text": "b x c"}]
    reports = list(run_documents(validation_documents(rows), {"a": ["b"]},
                                 checkpoints=(2,), limit=4, top_n=0))
    assert [r["kind"] for r in reports] == ["checkpoint", "limit"]
    assert reports[-1]["processed_token_occurrences"] == 4
    assert reports[-1]["graph_concepts"] == 3
    assert reports[-1]["queries"][0]["jaccard"]["controls"][0]["score"] == 1.0
    assert reports[-1]["queries"][0]["jaccard"]["top"] == []


def test_rank_validation():
    _, a = manual()
    for metric, top_n in [("other", 1), ("cosine", -1), ("jaccard", True)]:
        with pytest.raises(ValueError):
            a.rank(a.token_ids["a"], metric, top_n)


def test_local_cli(tmp_path):
    document = tmp_path / "text.txt"
    queries = tmp_path / "queries.json"
    document.write_text("a x b x", encoding="utf-8")
    queries.write_text('{"a": ["b"]}', encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "neuroliq.m6_3", "--files", str(document),
                             "--queries", str(queries), "--checkpoints", "2", "4",
                             "--limit", "4", "--top-n", "1"], capture_output=True, check=True)
    reports = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r["processed_token_occurrences"] for r in reports] == [2, 4]
    assert reports[-1]["queries"][0]["jaccard"]["top"] == [{"token_key": "b", "score": 1.0}]
