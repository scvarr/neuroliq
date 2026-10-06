"""M6.2: сырой граф текстовых форм и отдельная статистика наблюдений."""

import argparse
from collections import Counter
from collections.abc import Iterable, Iterator
import json
from pathlib import Path
import unicodedata

from neuroliq.graph import ConceptId, Graph

BASELINE_STRENGTH = 1.0
DEFAULT_CHECKPOINTS = (10_000, 100_000, 1_000_000, 10_000_000)
CONNECTORS = frozenset("-'’_")
TokenPair = tuple[str, str]


def tokenize(text: str) -> Iterator[str]:
    """NFC, группы L/N/M и внутренние соединители; identity после casefold."""
    text = unicodedata.normalize("NFC", text)

    def part(start: int) -> tuple[int, bool]:
        end = start
        has_alphanumeric = False
        while end < len(text):
            category = unicodedata.category(text[end])[0]
            if category not in "LNM":
                break
            has_alphanumeric |= category in "LN"
            end += 1
        return end, has_alphanumeric

    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        end, has_alphanumeric = part(index)
        if end == index:
            yield text[index].casefold()
            index += 1
            continue
        while has_alphanumeric and end < len(text) and text[end] in CONNECTORS:
            next_end, next_has_alphanumeric = part(end + 1)
            if not next_has_alphanumeric:
                break
            end = next_end
            has_alphanumeric = next_has_alphanumeric
        yield text[index:end].casefold()
        index = end


def canonical_pair(a: str, b: str) -> TokenPair:
    """Канонический порядок Unicode token keys, независимый от UUID."""
    return (a, b) if a <= b else (b, a)


class RawTextBaseline:
    """Отдельный стенд; граф и счётчики принадлежат одному запуску."""

    def __init__(
        self, checkpoints: Iterable[int] = DEFAULT_CHECKPOINTS, top_n: int = 10
    ) -> None:
        self.checkpoints = tuple(checkpoints)
        if any(type(n) is not int or n <= 0 for n in self.checkpoints):
            raise ValueError("Checkpoints должны быть положительными целыми числами")
        if tuple(sorted(set(self.checkpoints))) != self.checkpoints:
            raise ValueError("Checkpoints должны строго возрастать")
        if type(top_n) is not int or top_n < 0:
            raise ValueError("top_n должен быть неотрицательным целым числом")
        self.top_n = top_n
        self.graph = Graph()
        self.token_ids: dict[str, ConceptId] = {}
        self.token_counts: Counter[str] = Counter()
        self.pair_counts: Counter[TokenPair] = Counter()
        self.processed_tokens = 0
        self.repeated_nodes = 0
        self.repeated_pairs = 0
        self.self_pairs = 0
        self.connection_count = 0
        self._checkpoint_index = 0
        self._previous_checkpoint = (0, 0, 0, 0)

    def ingest_document(self, text: str) -> Iterator[dict]:
        """Обработать целый документ; выдавать snapshot точно после N токенов."""
        previous: str | None = None
        for key in tokenize(text):
            if key in self.token_ids:
                self.repeated_nodes += 1
            else:
                self.token_ids[key] = self.graph.create_concept().id
            self.token_counts[key] += 1
            self.processed_tokens += 1
            if previous is not None:
                pair = canonical_pair(previous, key)
                if previous == key:
                    self.self_pairs += 1
                elif self.pair_counts[pair]:
                    self.repeated_pairs += 1
                else:
                    self.graph.create_connection(
                        self.token_ids[previous], self.token_ids[key], BASELINE_STRENGTH
                    )
                    self.connection_count += 1
                self.pair_counts[pair] += 1
            previous = key
            if (
                self._checkpoint_index < len(self.checkpoints)
                and self.processed_tokens == self.checkpoints[self._checkpoint_index]
            ):
                snapshot = self.snapshot(final=False)
                self._previous_checkpoint = self._totals()
                self._checkpoint_index += 1
                yield snapshot

    def _totals(self) -> tuple[int, int, int, int]:
        return (
            len(self.token_ids), self.connection_count,
            self.repeated_nodes, self.repeated_pairs,
        )

    def snapshot(self, *, final: bool = True) -> dict:
        """Копия статистики; дельты от последнего checkpoint, чтение без мутаций."""
        degrees = {
            key: len(self.graph.neighbors(self.token_ids[key]))
            for key in sorted(self.token_ids)
        }
        distribution = Counter(degrees.values())
        delta = tuple(a - b for a, b in zip(self._totals(), self._previous_checkpoint))
        report = {
            "kind": "final" if final else "checkpoint",
            "processed_token_occurrences": self.processed_tokens,
            "unique_normalized_tokens": len(self.token_ids),
            "graph_concepts": len(self.token_ids),
            "unique_graph_connections": self.connection_count,
            "observed_pair_occurrences": sum(self.pair_counts.values()),
            "unique_observed_pairs": len(self.pair_counts),
            "repeated_node_occurrences": self.repeated_nodes,
            "repeated_pair_occurrences": self.repeated_pairs,
            "self_pair_occurrences": self.self_pairs,
            "singleton_token_keys": sum(n == 1 for n in self.token_counts.values()),
            "singleton_observed_pairs": sum(n == 1 for n in self.pair_counts.values()),
            "degree_distribution": [
                {"degree": degree, "nodes": distribution[degree]}
                for degree in sorted(distribution)
            ],
            "top_frequent": [
                {"token_key": key, "occurrence_count": count}
                for key, count in sorted(
                    self.token_counts.items(), key=lambda item: (-item[1], item[0])
                )[:self.top_n]
            ],
            "top_connected": [
                {"token_key": key, "degree": degree}
                for key, degree in sorted(
                    degrees.items(), key=lambda item: (-item[1], item[0])
                )[:self.top_n]
            ],
            "delta": dict(zip((
                "new_unique_nodes", "new_unique_connections",
                "repeated_node_occurrences", "repeated_pair_occurrences",
            ), delta)),
        }
        if final:
            report["token_occurrence_counts"] = dict(sorted(self.token_counts.items()))
            report["pair_occurrence_counts"] = [
                {"token_keys": list(pair), "occurrence_count": count}
                for pair, count in sorted(self.pair_counts.items())
            ]
            report["degrees"] = degrees
        return report


def run_files(
    paths: Iterable[Path], checkpoints: Iterable[int] = DEFAULT_CHECKPOINTS,
    top_n: int = 10,
) -> Iterator[dict]:
    """Локальные UTF-8 .txt: каждый файл — отдельный документ, порядок задан явно."""
    baseline = RawTextBaseline(checkpoints, top_n)
    for path in paths:
        path = Path(path)
        if path.suffix.lower() != ".txt":
            raise ValueError("Входной файл должен иметь расширение .txt")
        yield from baseline.ingest_document(path.read_text(encoding="utf-8"))
    yield baseline.snapshot()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="M6.2: сырой граф текстовых форм; статистика в JSON Lines"
    )
    parser.add_argument("files", type=Path, nargs="+", help="Локальные UTF-8 .txt")
    parser.add_argument(
        "--checkpoints", type=int, nargs="+", default=DEFAULT_CHECKPOINTS,
        help="Строго возрастающие количества обработанных токенов",
    )
    parser.add_argument("--top-n", type=int, default=10, help="Размер обоих top-N")
    args = parser.parse_args()
    try:
        for snapshot in run_files(args.files, args.checkpoints, args.top_n):
            print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), flush=True)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(2, f"Ошибка M6.2: {error}\n")


if __name__ == "__main__":
    main()
