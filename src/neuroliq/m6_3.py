"""M6.3: две прозрачные меры сходства 1-hop surface-профилей."""

import argparse
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
import json
from math import sqrt
from pathlib import Path

from neuroliq.graph import ConceptId
from neuroliq.m6_2 import RawTextBaseline

CHECKPOINTS = (100_000, 250_000, 500_000)


@dataclass
class Profile:
    """Координаты — ConceptId соседей; вес — число наблюдений пары M6.2."""

    concept_id: ConceptId
    weights: dict[ConceptId, int]
    frequency: int

    @property
    def neighbors(self) -> frozenset[ConceptId]:
        return frozenset(self.weights)

    @property
    def degree(self) -> int:
        return len(self.weights)


def jaccard(a: Profile, b: Profile) -> float:
    union = a.neighbors | b.neighbors
    return len(a.neighbors & b.neighbors) / len(union) if union else 0.0


def cosine(a: Profile, b: Profile) -> float:
    """Сырые целочисленные частоты; нулевой профиль даёт score=0."""
    aa = sum(w * w for w in a.weights.values())
    bb = sum(w * w for w in b.weights.values())
    dot = sum(w * b.weights.get(n, 0) for n, w in a.weights.items())
    return dot / sqrt(aa * bb) if aa and bb else 0.0


class StructuralAnalysis:
    """Независимый снимок профилей; labels нужны для lookup, ничьих и вывода."""

    def __init__(self, baseline: RawTextBaseline) -> None:
        self.token_ids = dict(baseline.token_ids)
        self.labels = {cid: key for key, cid in self.token_ids.items()}
        self.profiles = {
            cid: Profile(cid, {}, baseline.token_counts[key])
            for key, cid in self.token_ids.items()
        }
        for (a, b), count in baseline.pair_counts.items():
            if a == b:
                continue
            ca, cb = self.token_ids[a], self.token_ids[b]
            self.profiles[ca].weights[cb] = count
            self.profiles[cb].weights[ca] = count

    def rank(self, query_id: ConceptId, metric: str,
             top_n: int | None = None) -> list[tuple[ConceptId, float]]:
        if metric not in ("jaccard", "cosine"):
            raise ValueError("Метрика должна быть jaccard или cosine")
        if top_n is not None and (type(top_n) is not int or top_n < 0):
            raise ValueError("top_n должен быть неотрицательным целым числом")
        query = self.profiles[query_id]
        measure = jaccard if metric == "jaccard" else cosine
        numeric = [(cid, measure(query, p)) for cid, p in self.profiles.items()
                   if cid != query_id]
        numeric.sort(key=lambda row: (-row[1], self.labels[row[0]]))
        return numeric if top_n is None else numeric[:top_n]

    def diagnose(self, key: str, *, top_n: int = 10,
                 controls: Iterable[str] = ()) -> dict:
        if type(top_n) is not int or top_n < 0:
            raise ValueError("top_n должен быть неотрицательным целым числом")
        if key not in self.token_ids:
            return {"token_key": key, "present": False}
        cid = self.token_ids[key]
        p = self.profiles[cid]
        report = {"token_key": key, "present": True, "frequency": p.frequency,
                  "degree": p.degree, "top_neighbors": [
                      {"token_key": self.labels[n], "pair_count": w}
                      for n, w in sorted(p.weights.items(),
                                         key=lambda row: (-row[1], self.labels[row[0]]))[:top_n]
                  ]}
        controls = tuple(controls)
        for metric in ("jaccard", "cosine"):
            ranking = self.rank(cid, metric)
            positions = {c: (i, score) for i, (c, score) in enumerate(ranking, 1)}
            report[metric] = {
                "top": [{"token_key": self.labels[c], "score": score}
                        for c, score in ranking[:top_n]],
                "controls": [{"token_key": control,
                              "present": control in self.token_ids,
                              "rank": positions.get(self.token_ids.get(control), (None, None))[0],
                              "score": positions.get(self.token_ids.get(control), (None, None))[1]}
                             for control in controls if control != key],
            }
        return report


def run_documents(documents: Iterable[str], queries: Mapping[str, Iterable[str]], *,
                  checkpoints: Iterable[int] = CHECKPOINTS, limit: int = 500_000,
                  top_n: int = 10) -> Iterator[dict]:
    """Остановить генератор M6.2 на точном лимите, включая входящее соседство."""
    checkpoints = tuple(checkpoints)
    RawTextBaseline(checkpoints, top_n)  # Проверка контракта параметров M6.2.
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit должен быть положительным целым числом")
    if checkpoints and checkpoints[-1] > limit:
        raise ValueError("Checkpoint превышает limit")
    queries = {key: tuple(controls) for key, controls in queries.items()}
    baseline = RawTextBaseline(sorted(set((*checkpoints, limit))), top_n)

    def report(kind: str) -> dict:
        analysis = StructuralAnalysis(baseline)
        return {"kind": kind, "processed_token_occurrences": baseline.processed_tokens,
                "graph_concepts": len(baseline.token_ids),
                "graph_connections": baseline.connection_count,
                "self_pair_occurrences": baseline.self_pairs,
                "queries": [analysis.diagnose(key, top_n=top_n, controls=controls)
                            for key, controls in queries.items()]}

    for document in documents:
        for snapshot in baseline.ingest_document(document):
            size = snapshot["processed_token_occurrences"]
            if size in checkpoints:
                yield report("checkpoint")
            if size == limit:
                if size not in checkpoints:
                    yield report("limit")
                return
    yield report("final")


def main() -> None:
    parser = argparse.ArgumentParser(description="M6.3: структурное сходство surface-узлов")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--files", nargs="+", type=Path, help="Локальные UTF-8 документы")
    source.add_argument("--dataset", action="store_true", help="Фиксированный validation корпуса")
    parser.add_argument("--queries", type=Path, required=True,
                        help="JSON: token key → список контрольных ключей")
    parser.add_argument("--checkpoints", nargs="+", type=int, default=CHECKPOINTS)
    parser.add_argument("--limit", type=int, default=500_000)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()
    try:
        queries = json.loads(args.queries.read_text(encoding="utf-8"))
        if not isinstance(queries, dict) or any(
            not isinstance(k, str) or not isinstance(v, list)
            or any(not isinstance(c, str) for c in v) for k, v in queries.items()
        ):
            raise ValueError("Queries должны быть объектом со списками строк")
        if args.dataset:
            from neuroliq.m6_3_dataset import validation_documents
            documents = validation_documents()
        else:
            documents = (path.read_text(encoding="utf-8") for path in args.files)
        for snapshot in run_documents(documents, queries, checkpoints=args.checkpoints,
                                      limit=args.limit, top_n=args.top_n):
            print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), flush=True)
    except (OSError, ValueError, ImportError) as error:
        parser.exit(2, f"Ошибка M6.3: {error}\n")


if __name__ == "__main__":
    main()
