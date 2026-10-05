"""Внешнее текстовое представление структуры графа."""

import json
from collections.abc import Mapping

from .graph import ConceptId, Graph


def diagnostic_snapshot(
    graph: Graph, labels: Mapping[ConceptId, str] | None = None
) -> str:
    """Сортировка по UUID исключает зависимость от порядка добавления структуры."""
    labels = {} if labels is None else labels
    concepts = sorted(graph.concepts(), key=lambda concept: concept.id.int)
    connections = sorted(
        graph.connections(), key=lambda edge: (edge.concept_a.int, edge.concept_b.int)
    )
    lines = [f"Концепты ({len(concepts)}):"]
    for concept in concepts:
        label = ""
        if concept.id in labels:
            label = " " + json.dumps(labels[concept.id], ensure_ascii=False)
        lines.append(f"  {concept.id}{label}")
    lines.append(f"Связи ({len(connections)}, неориентированные):")
    for edge in connections:
        lines.append(f"  {edge.concept_a} -- {edge.concept_b}: {edge.strength!r}")
    return "\n".join(lines)
