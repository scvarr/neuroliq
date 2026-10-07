"""Постоянный скелет L0 и внешний словарь в SQLite workspace."""

import json
import unicodedata
from uuid import uuid4


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS l0_concepts (id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS lexical_dictionary (
            surface TEXT PRIMARY KEY, concept_id TEXT NOT NULL REFERENCES l0_concepts(id));
        CREATE INDEX IF NOT EXISTS lexical_dictionary_concept ON lexical_dictionary(concept_id);
        CREATE TABLE IF NOT EXISTS l0_connections (
            concept_a TEXT NOT NULL REFERENCES l0_concepts(id),
            concept_b TEXT NOT NULL REFERENCES l0_concepts(id),
            PRIMARY KEY(concept_a, concept_b), CHECK(concept_a < concept_b));
        CREATE INDEX IF NOT EXISTS l0_connections_b ON l0_connections(concept_b);
        CREATE TABLE IF NOT EXISTS corpus_cursors (corpus TEXT PRIMARY KEY, data TEXT NOT NULL);
    """)


def cursor(db, corpus):
    row = db.execute("SELECT data FROM corpus_cursors WHERE corpus=?", (corpus,)).fetchone()
    return json.loads(row[0]) if row else {"row": 0, "ordinal": 0, "previous_concept": None}


def project(db, workspace, previous=None):
    """Топология производна от сохранённых occurrences; строки остаются снаружи."""
    current_source = None
    for occurrence in workspace["occurrences"]:
        key = occurrence["key"]
        row = db.execute("SELECT concept_id FROM lexical_dictionary WHERE surface=?", (key,)).fetchone()
        concept = row[0] if row else str(uuid4())
        if row is None:
            db.execute("INSERT INTO l0_concepts VALUES (?)", (concept,))
            db.execute("INSERT INTO lexical_dictionary VALUES (?, ?)", (key, concept))
        if current_source != occurrence["source_id"]:
            if current_source is not None or occurrence["ordinal"] == 0:
                previous = None
            current_source = occurrence["source_id"]
        if previous is not None and previous != concept:
            db.execute("INSERT OR IGNORE INTO l0_connections VALUES (?, ?)", tuple(sorted((previous, concept))))
        previous = concept
    return previous


def stats(db):
    return {"concepts": db.execute("SELECT COUNT(*) FROM l0_concepts").fetchone()[0],
            "connections": db.execute("SELECT COUNT(*) FROM l0_connections").fetchone()[0],
            "dictionary_forms": db.execute("SELECT COUNT(*) FROM lexical_dictionary").fetchone()[0],
            "corpus_cursors": [{"corpus": key, **json.loads(data)} for key, data in
                               db.execute("SELECT corpus, data FROM corpus_cursors ORDER BY corpus")]}


def dictionary(db, query, limit):
    query = unicodedata.normalize("NFC", query).casefold()
    # LIKE использует литеральную строку запроса, включая %, _ и обратную косую черту.
    pattern = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.execute("SELECT surface, concept_id FROM lexical_dictionary "
                      "WHERE surface LIKE ? ESCAPE '\\' ORDER BY surface LIMIT ?", (pattern + "%", limit + 1)).fetchall()
    return {"entries": [{"surface": s, "concept_id": c} for s, c in rows[:limit]],
            "truncated": len(rows) > limit}


def neighborhood(db, concept, limit):
    if db.execute("SELECT 1 FROM l0_concepts WHERE id=?", (concept,)).fetchone() is None:
        raise KeyError("ConceptId не найден")
    query = "SELECT concept_b FROM l0_connections WHERE concept_a=? UNION ALL SELECT concept_a FROM l0_connections WHERE concept_b=?"
    neighbors = [r[0] for r in db.execute(query + " ORDER BY 1 LIMIT ?", (concept, concept, limit + 1))]
    degree = db.execute("SELECT COUNT(*) FROM (" + query + ")", (concept, concept)).fetchone()[0]
    ids = [concept, *neighbors[:limit]]
    placeholders = ",".join("?" for _ in ids)
    connections = [{"concept_a": a, "concept_b": b} for a, b in db.execute(
        f"SELECT concept_a, concept_b FROM l0_connections WHERE concept_a IN ({placeholders}) "
        f"AND concept_b IN ({placeholders}) ORDER BY concept_a, concept_b", ids + ids)]
    return {"center": concept, "degree": degree, "truncated": len(neighbors) > limit,
            "concepts": [{"id": i} for i in ids], "connections": connections,
            "dictionary": [{"surface": s, "concept_id": c} for s, c in db.execute(
                f"SELECT surface, concept_id FROM lexical_dictionary WHERE concept_id IN ({placeholders}) ORDER BY surface", ids)]}
