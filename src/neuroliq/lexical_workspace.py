"""Локальные проверяемые семьи; не проекция на Graph и не семантический L0."""

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from uuid import uuid4

from .m6_2 import tokenize

GENERATOR = "ru-surface-prefix-v1"
RULE = ("Только русские формы длиной ≥4 с частотой ≥2. Общий префикс ≥4; "
        "остаток каждой формы ≤3 символов. Сначала самые длинные префиксы, "
        "без транзитивного объединения. Остальные повторные формы — отдельные семьи. "
        "Совпадение строки не доказывает общий смысл или фактор.")


def now():
    return datetime.now(timezone.utc).isoformat()


def build_workspace(documents, limit=10_000, title="Русский батч"):
    """Точный bounded-батч; документы — пары (ссылка источника, текст)."""
    if type(limit) is not int or limit < 1:
        raise ValueError("Лимит должен быть положительным целым числом")
    sources, occurrences = [], []
    for reference, original in documents:
        text = unicodedata.normalize("NFC", original)
        # Карта casefold сохраняет позиции даже при расширении Unicode символа.
        folded, positions = [], []
        for index, char in enumerate(text):
            folded.append(char.casefold())
            positions.extend([index] * len(char.casefold()))
        folded = "".join(folded)
        cursor = 0
        source_id = len(sources)
        sources.append({"id": source_id, "reference": reference, "text": text,
                        "original_text": original,
                        "sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                        "normalization": "NFC", "processed_tokens": 0})
        for ordinal, key in enumerate(tokenize(text)):
            start = folded.index(key, cursor)
            end = start + len(key)
            occurrences.append({"id": len(occurrences), "source_id": source_id,
                                "ordinal": ordinal, "key": key,
                                "start": positions[start], "end": positions[end - 1] + 1})
            sources[-1]["processed_tokens"] += 1
            cursor = end
            if len(occurrences) == limit:
                break
        if len(occurrences) == limit:
            break
    counts = Counter(o["key"] for o in occurrences)
    eligible = {k for k, count in counts.items() if count >= 2 and re.fullmatch(r"[а-яё]{4,}", k)}
    buckets = defaultdict(set)
    for key in sorted(eligible):
        for length in range(max(4, len(key) - 3), len(key) + 1):
            buckets[key[:length]].add(key)
    groups, used = [], set()
    for prefix in sorted(buckets, key=lambda p: (-len(p), p)):
        forms = buckets[prefix] - used
        if len(forms) >= 2:
            groups.append((prefix, sorted(forms), "prefix"))
            used.update(forms)
    groups.extend((k, [k], "exact") for k in sorted(eligible - used))
    by_key = defaultdict(list)
    for o in occurrences:
        by_key[o["key"]].append(o["id"])
    families = []
    for prefix, forms, kind in groups:
        members = sorted(i for k in forms for i in by_key[k])
        family_id = "f-" + hashlib.sha256(json.dumps(forms, ensure_ascii=False).encode()).hexdigest()[:16]
        families.append({"id": family_id, "prefix": prefix, "kind": kind, "forms": forms,
                         "members": members, "status": "pending", "shown": 8, "parent": None})
    families.sort(key=lambda f: (-len(f["forms"]), -len(f["members"]), f["forms"]))
    return {"id": str(uuid4()), "title": title, "created_at": now(), "revision": 0,
            "generator": GENERATOR, "rule": RULE, "requested_limit": limit,
            "parameters": {"min_frequency": 2, "min_prefix": 4, "max_tail": 3,
                           "eligible_pattern": "[а-яё]{4,}", "tokenizer": "M6.2 NFC/casefold",
                           "unicode_version": unicodedata.unidata_version},
            "sources": sources, "occurrences": occurrences, "families": families, "events": [],
            "diagnostics": {"processed_tokens": len(occurrences), "unique_forms": len(counts),
                            "grouped_occurrences": sum(len(f["members"]) for f in families),
                            "ungrouped_occurrences": len(occurrences) - sum(len(f["members"]) for f in families)}}


def evidence_order(workspace, family):
    """По форме, источнику и редкому локальному окружению; затем остальные."""
    occurrences = workspace["occurrences"]
    members = family["members"]
    signatures = {}
    for i in members:
        o = occurrences[i]
        s = workspace["sources"][o["source_id"]]["text"]
        signatures[i] = (s[max(0, o["start"] - 24):o["start"]], s[o["end"]:o["end"] + 24])
    frequencies = Counter(signatures.values())
    chosen, reasons = [], {}

    def add(i, reason):
        if i not in reasons:
            chosen.append(i)
            reasons[i] = reason

    for key in family["forms"]:
        add(next(i for i in members if occurrences[i]["key"] == key), "Представитель формы")
    for source in sorted({occurrences[i]["source_id"] for i in members}):
        add(next(i for i in members if occurrences[i]["source_id"] == source), "Другой источник")
    for i in sorted(members, key=lambda i: (frequencies[signatures[i]], i)):
        add(i, "Редкое окружение — проверить" if frequencies[signatures[i]] == 1 else "Дополнительный пример")
    return chosen, reasons


def family_view(workspace, family):
    order, reasons = evidence_order(workspace, family)
    examples = []
    for i in order[:family["shown"]]:
        o = workspace["occurrences"][i]
        source = workspace["sources"][o["source_id"]]
        examples.append({**o, "reference": source["reference"], "reason": reasons[i],
                         "before": source["text"][max(0, o["start"] - 160):o["start"]],
                         "surface": source["text"][o["start"]:o["end"]],
                         "after": source["text"][o["end"]:o["end"] + 160]})
    return {**family, "members": None, "total": len(family["members"]),
            "form_counts": dict(Counter(workspace["occurrences"][i]["key"] for i in family["members"])),
            "examples": examples, "events": [e for e in workspace["events"]
                                               if e["family_id"] == family["id"] or e.get("child_id") == family["id"]]}


def review(workspace, family_id, action, reviewer, note="", selected=(), forms=()):
    family = next((f for f in workspace["families"] if f["id"] == family_id), None)
    if family is None:
        raise KeyError("Семья не найдена")
    if action not in ("accept", "reject", "split", "more"):
        raise ValueError("Неизвестное действие")
    if not reviewer.strip():
        raise ValueError("Укажите проверяющего")
    if action != "more" and family["status"] != "pending":
        raise ValueError("Решение уже принято; разделять можно только ожидающую семью")
    event = {"at": now(), "family_id": family_id, "action": action, "reviewer": reviewer,
             "note": note, "members_before": list(family["members"]),
             "inspected": evidence_order(workspace, family)[0][:family["shown"]],
             "revision": workspace["revision"] + 1}
    if action == "split":
        if not set(forms) <= set(family["forms"]) or not set(selected) <= set(family["members"]):
            raise ValueError("Выбраны примеры или формы вне семьи")
        moved = sorted(set(selected) | {i for i in family["members"]
                                       if workspace["occurrences"][i]["key"] in forms})
        if not moved or len(moved) == len(family["members"]):
            raise ValueError("Разделение должно оставить примеры в обеих семьях")
        child = {**family, "id": str(uuid4()), "members": moved, "parent": family_id,
                 "kind": "manual", "shown": 8}
        moved_set = set(moved)
        family["members"] = [i for i in family["members"] if i not in moved_set]
        for f in (family, child):
            f["forms"] = sorted({workspace["occurrences"][i]["key"] for i in f["members"]})
        workspace["families"].insert(workspace["families"].index(family) + 1, child)
        event.update(child_id=child["id"], moved=moved)
    elif action == "more":
        family["shown"] = min(len(family["members"]), family["shown"] + 8)
    else:
        family["status"] = "accepted" if action == "accept" else "rejected"
        if action == "accept":
            family["mapping_id"] = str(uuid4())
    workspace["events"].append(event)
    workspace["revision"] += 1


def mappings(workspace):
    """Массовая occurrence-проекция workspace; никаких грамматических меток."""
    return [{"family_id": f["id"], "mapping_id": f["mapping_id"], "occurrence_ids": f["members"]}
            for f in workspace["families"] if f["status"] == "accepted"]


class WorkspaceStore:
    """SQLite: атомарный снимок батча, независимый от Graph Lab runtime."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, revision INTEGER, data TEXT)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connect() as db:
            return [{"id": w["id"], "title": w["title"], "created_at": w["created_at"],
                     "diagnostics": w["diagnostics"]}
                    for (data,) in db.execute("SELECT data FROM workspaces ORDER BY rowid DESC")
                    for w in [json.loads(data)]]

    def load(self, workspace_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        if row is None:
            raise KeyError("Батч не найден")
        return json.loads(row[0])

    def create(self, workspace):
        with self.connect() as db:
            db.execute("INSERT INTO workspaces VALUES (?, ?, ?)",
                       (workspace["id"], workspace["revision"], json.dumps(workspace, ensure_ascii=False)))

    def decide(self, workspace_id, revision, **kwargs):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
            if row is None:
                raise KeyError("Батч не найден")
            workspace = json.loads(row[0])
            if revision != workspace["revision"]:
                raise RuntimeError("Батч изменился в другой вкладке. Обновите страницу")
            review(workspace, **kwargs)
            db.execute("UPDATE workspaces SET revision=?, data=? WHERE id=?",
                       (workspace["revision"], json.dumps(workspace, ensure_ascii=False), workspace_id))
        return workspace
