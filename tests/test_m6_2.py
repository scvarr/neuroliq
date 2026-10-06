import json
from pathlib import Path
import subprocess
import sys

import pytest

from neuroliq.m6_2 import (
    BASELINE_STRENGTH, DEFAULT_CHECKPOINTS, RawTextBaseline,
    canonical_pair, run_files, tokenize,
)

FIXTURE = Path(__file__).resolve().parents[1] / "experiments/m6-2-raw-text.txt"


@pytest.mark.parametrize(("text", "expected"), [
    ("Иван любит яблоки.", ["иван", "любит", "яблоки", "."]),
    ("«Иван», — сказал Павел.", ["«", "иван", "»", ",", "—", "сказал", "павел", "."]),
    ("из-за GPT-5", ["из-за", "gpt-5"]),
    ("x = y + 2", ["x", "=", "y", "+", "2"]),
    ("f(x)=x²+2x-1", ["f", "(", "x", ")", "=", "x²", "+", "2x-1"]),
    ("про\nграммирования", ["про", "граммирования"]),
    (" \t\r\n\u00a0\u2003", []),
    ("É E\u0301 Straße STRASSE", ["é", "é", "strasse", "strasse"]),
    ("İ i\u0307", ["i\u0307", "i\u0307"]),
    ("中文१२३ a\u0308\u0323", ["中文१२३", "ạ\u0308"]),
    ("-a a- a--b _x x_ 'x' ’x’", [
        "-", "a", "a", "-", "a", "-", "-", "b", "_", "x", "x", "_",
        "'", "x", "'", "’", "x", "’",
    ]),
    ("l'amour l’amour a_b a-b-c 1_2", ["l'amour", "l’amour", "a_b", "a-b-c", "1_2"]),
    ("\u0301-\u0300 a-\u0301b a-\u0301", ["\u0301", "-", "\u0300", "a-\u0301b", "a", "-", "\u0301"]),
    ("https://a.b 2026/10/06", ["https", ":", "/", "/", "a", ".", "b", "2026", "/", "10", "/", "06"]),
    ("😀!?", ["😀", "!", "?"]),
])
def test_exact_tokenizer_contract(text, expected):
    assert list(tokenize(text)) == expected


def consume(*documents, checkpoints=(), top_n=10):
    baseline = RawTextBaseline(checkpoints, top_n)
    snapshots = []
    for document in documents:
        snapshots.extend(baseline.ingest_document(document))
    snapshots.append(baseline.snapshot())
    return baseline, snapshots


def test_identity_forms_punctuation_and_whitespace():
    baseline, reports = consume("Иван ИВАН иван студент студенты студентов . , \t\n")
    assert set(baseline.token_ids) == {
        "иван", "студент", "студенты", "студентов", ".", ",",
    }
    assert len(set(baseline.token_ids.values())) == 6
    ivan = baseline.token_ids["иван"]
    list(baseline.ingest_document("ИВАН"))
    assert baseline.token_ids["иван"] == ivan
    assert baseline.token_counts["иван"] == 4
    assert reports[-1]["processed_token_occurrences"] == 8
    assert reports[-1]["graph_concepts"] == 6


def test_reverse_and_repeated_adjacency_reuse_connection_without_strength_learning():
    baseline, _ = consume("A b")
    a, b = baseline.token_ids["a"], baseline.token_ids["b"]
    edge = baseline.graph.get_connection(a, b)
    list(baseline.ingest_document("B a b a"))
    assert baseline.graph.get_connection(b, a) is edge
    assert baseline.graph.get_connection(a, b) is edge
    assert baseline.graph.connections() == (edge,)
    assert edge.strength == BASELINE_STRENGTH == 1.0
    assert baseline.graph.neighbors(a) == (b,)
    assert baseline.graph.neighbors(b) == (a,)
    assert baseline.pair_counts == {("a", "b"): 4}
    assert baseline.repeated_pairs == 3
    assert baseline.repeated_nodes == 4


def test_self_pairs_are_observed_separately_without_graph_mutation():
    baseline, reports = consume("A a A")
    report = reports[-1]
    assert baseline.graph.connections() == ()
    assert baseline.graph.neighbors(baseline.token_ids["a"]) == ()
    assert baseline.pair_counts == {("a", "a"): 2}
    assert report["self_pair_occurrences"] == 2
    assert report["repeated_pair_occurrences"] == 0
    assert report["degrees"] == {"a": 0}
    assert report["degree_distribution"] == [{"degree": 0, "nodes": 1}]
    assert report["singleton_observed_pairs"] == 0


def test_document_boundaries_reset_previous_even_across_empty_documents():
    baseline, reports = consume("a", "", " \n", "b c", "d")
    assert baseline.pair_counts == {("b", "c"): 1}
    assert reports[-1]["degrees"] == {"a": 0, "b": 1, "c": 1, "d": 0}
    assert baseline.graph.get_connection(baseline.token_ids["a"], baseline.token_ids["b"]) is None


def test_exact_checkpoints_deltas_final_and_independent_snapshots():
    baseline, reports = consume("A b a a b", "B c", checkpoints=(2, 4, 6))
    assert [r["processed_token_occurrences"] for r in reports] == [2, 4, 6, 7]
    assert [r["kind"] for r in reports] == ["checkpoint"] * 3 + ["final"]
    assert [list(r["delta"].values()) for r in reports] == [
        [2, 1, 0, 0], [0, 0, 2, 1], [0, 0, 2, 1], [1, 1, 0, 0],
    ]
    final = reports[-1]
    assert final["token_occurrence_counts"] == {"a": 3, "b": 3, "c": 1}
    assert final["pair_occurrence_counts"] == [
        {"token_keys": ["a", "a"], "occurrence_count": 1},
        {"token_keys": ["a", "b"], "occurrence_count": 3},
        {"token_keys": ["b", "c"], "occurrence_count": 1},
    ]
    assert final["unique_graph_connections"] == len(baseline.graph.connections()) == 2
    assert final["graph_concepts"] == len(baseline.graph.concepts()) == 3
    assert final["observed_pair_occurrences"] == 5
    assert final["unique_observed_pairs"] == 3
    assert final["singleton_token_keys"] == 1
    assert final["singleton_observed_pairs"] == 2
    assert final["degrees"] == {"a": 1, "b": 2, "c": 1}
    assert final["degree_distribution"] == [{"degree": 1, "nodes": 2}, {"degree": 2, "nodes": 1}]
    assert final["top_frequent"] == [
        {"token_key": "a", "occurrence_count": 3},
        {"token_key": "b", "occurrence_count": 3},
        {"token_key": "c", "occurrence_count": 1},
    ]
    assert final["top_connected"] == [
        {"token_key": "b", "degree": 2},
        {"token_key": "a", "degree": 1},
        {"token_key": "c", "degree": 1},
    ]
    assert baseline.snapshot() == final
    list(baseline.ingest_document("d"))
    assert reports[0]["graph_concepts"] == 2
    assert final["token_occurrence_counts"] == {"a": 3, "b": 3, "c": 1}


def test_statistics_are_uuid_independent_and_top_n_ties_are_lexical():
    first, reports = consume("z b a b", checkpoints=(1, 3), top_n=2)
    second, again = consume("z b a b", checkpoints=(1, 3), top_n=2)
    assert set(first.token_ids.values()).isdisjoint(second.token_ids.values())
    assert reports == again
    assert reports[-1]["top_frequent"] == [
        {"token_key": "b", "occurrence_count": 2}, {"token_key": "a", "occurrence_count": 1},
    ]
    assert canonical_pair("z", "a") == canonical_pair("a", "z") == ("a", "z")


@pytest.mark.parametrize("documents,checkpoints,counts", [
    (("",), (2,), [0]), (("a",), (2,), [1]),
    (("a b",), (2,), [2, 2]), (("a b c",), (), [3]),
])
def test_final_is_always_emitted_including_empty_and_exact_checkpoint(documents, checkpoints, counts):
    _, reports = consume(*documents, checkpoints=checkpoints)
    assert [r["processed_token_occurrences"] for r in reports] == counts
    assert reports[-1]["kind"] == "final"
    if counts == [2, 2]:
        assert set(reports[-1]["delta"].values()) == {0}


def test_default_large_checkpoints_do_not_require_large_input():
    assert DEFAULT_CHECKPOINTS == (10_000, 100_000, 1_000_000, 10_000_000)
    assert RawTextBaseline().checkpoints == DEFAULT_CHECKPOINTS
    assert len(list(run_files([FIXTURE]))) == 1


@pytest.mark.parametrize("checkpoints", [(0,), (-1,), (True,), (1.5,), (2, 1), (1, 1)])
def test_invalid_checkpoints_are_rejected(checkpoints):
    with pytest.raises(ValueError):
        RawTextBaseline(checkpoints)


@pytest.mark.parametrize("top_n", [-1, True, 1.5])
def test_invalid_top_n_is_rejected(top_n):
    with pytest.raises(ValueError):
        RawTextBaseline(top_n=top_n)


def test_zero_top_n_keeps_counts():
    _, reports = consume("a", top_n=0)
    assert reports[-1]["top_frequent"] == reports[-1]["top_connected"] == []
    assert reports[-1]["token_occurrence_counts"] == {"a": 1}


def test_utf8_files_are_separate_documents_and_decoding_is_strict(tmp_path):
    first, second = tmp_path / "one.txt", tmp_path / "two.txt"
    first.write_text("ИВАН", encoding="utf-8")
    second.write_text("Павел", encoding="utf-8")
    report = list(run_files([first, second]))[-1]
    assert report["unique_graph_connections"] == 0
    assert report["token_occurrence_counts"] == {"иван": 1, "павел": 1}
    second.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        list(run_files([second]))
    with pytest.raises(ValueError):
        list(run_files([tmp_path / "wrong.csv"]))


def test_cli_fixture_matches_api_including_checkpoints():
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "neuroliq.m6_2", str(FIXTURE),
         "--checkpoints", "10", "20", "30", "--top-n", "3"],
        check=True, capture_output=True, encoding="utf-8",
    )
    assert [json.loads(line) for line in result.stdout.splitlines()] == list(
        run_files([FIXTURE], (10, 20, 30), 3)
    )


def test_fixture_has_exact_diagnostic_result_and_accounting_invariants():
    report = list(run_files([FIXTURE]))[-1]
    expected = {
        "processed_token_occurrences": 38, "graph_concepts": 27,
        "unique_normalized_tokens": 27, "unique_graph_connections": 34,
        "repeated_node_occurrences": 11, "repeated_pair_occurrences": 2,
        "self_pair_occurrences": 1, "observed_pair_occurrences": 37,
        "unique_observed_pairs": 35, "singleton_token_keys": 20,
        "singleton_observed_pairs": 33,
    }
    assert {key: report[key] for key in expected} == expected
    assert sum(report["token_occurrence_counts"].values()) == 38
    assert sum(pair["occurrence_count"] for pair in report["pair_occurrence_counts"]) == 37
    assert sum(report["degrees"].values()) == 2 * 34
    assert report["degree_distribution"] == [
        {"degree": 2, "nodes": 21}, {"degree": 3, "nodes": 1},
        {"degree": 4, "nodes": 3}, {"degree": 5, "nodes": 1},
        {"degree": 6, "nodes": 1},
    ]
