"""Одна общая основа и ограниченная постоянная память контекстных конструкций."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from .representation import Invalid, canonical, catalog, catalog_data, dumps, validate


class Memory:
    def __init__(self):
        self.concepts = catalog()
        self.contexts = {}
        self.records = {}
        self.revision = 0

    def context(self, key, parent=None, mode="source"):
        if not isinstance(key, str) or not key or len(key) > 256 or key in self.contexts:
            raise Invalid("Пустой или повторный контекст")
        if parent is not None and not isinstance(parent, str):
            raise Invalid("Недопустимый родитель контекста")
        if len(self.contexts) >= 1000 or (parent is not None and parent not in self.contexts):
            raise Invalid("Недопустимый родитель/бюджет контекста")
        if mode not in ("source", "belief", "hypothesis", "abstract"):
            raise Invalid("Неизвестный режим области")
        current, depth = parent, 1
        while current is not None:
            depth += 1
            if depth > 16:
                raise Invalid("Исчерпан бюджет вложенности контекста")
            current = self.contexts[current]["parent"]
        self.contexts[key] = {"parent": parent, "mode": mode}
        self.revision += 1

    def add(self, key, context, scene, provenance, status="accepted", kind="observation", split="test"):
        if not isinstance(key, str) or not key or ":" in key or key in self.records:
            raise Invalid("Недопустимый или повторный адрес записи")
        if len(self.records) >= 1000 or context not in self.contexts:
            raise Invalid("Недопустимый контекст/бюджет памяти")
        if status not in ("accepted", "proposed") or kind not in ("observation", "abstract"):
            raise Invalid("Недопустимый статус/вид записи")
        if split not in ("train", "validation", "test"):
            raise Invalid("Недопустимое разделение данных")
        if not isinstance(provenance, list) or not provenance:
            raise Invalid("Отсутствует происхождение")
        for source in provenance:
            if not isinstance(source, dict) or set(source) != {"source", "language", "text", "interpretation"}:
                raise Invalid("Недопустимое evidence")
            if not all(isinstance(v, str) and len(v) <= 4096 for v in source.values()):
                raise Invalid("Недопустимое значение evidence")
            if source["language"] not in ("ru", "en", "formal", "python"):
                raise Invalid("Недопустимый язык")
            if source["interpretation"] not in ("authored", "resolved", "ambiguous"):
                raise Invalid("Недопустимый статус интерпретации")
            if status == "accepted" and source["interpretation"] == "ambiguous":
                raise Invalid("Неоднозначная интерпретация требует proposed")
        normalized = canonical(scene, self.concepts)
        for declaration in normalized["entities"].values():
            if "origin" in declaration:
                address = declaration["origin"].split(":")
                if len(address) != 2 or address[0] not in self.records:
                    raise Invalid("Нет записи origin")
                target = self.records[address[0]]["scene"]["entities"].get(address[1])
                if target is None or any(target[k] != declaration[k] for k in ("concept", "value")):
                    raise Invalid("Origin не соответствует участнику")
                depth = 1
                while "origin" in target:
                    depth += 1
                    if depth > 16:
                        raise Invalid("Исчерпан бюджет цепочки origin")
                    record_id, local = target["origin"].split(":")
                    target = self.records[record_id]["scene"]["entities"][local]
        self.records[key] = deepcopy({"context": context, "scene": normalized, "provenance": provenance,
                                     "status": status, "kind": kind, "split": split})
        self.revision += 1
        return normalized

    def visible(self, context, descendants=False):
        if context not in self.contexts:
            raise Invalid("Неизвестная область запроса")
        result = {context}
        if descendants:
            for key in self.contexts:
                current = self.contexts[key]["parent"]
                while current is not None:
                    if current == context:
                        result.add(key)
                        break
                    current = self.contexts[current]["parent"]
        return result

    def patterns(self, split="train"):
        counts = Counter()
        support = {}
        for key, record in self.records.items():
            if record["split"] != split or record["status"] != "accepted":
                continue
            scene = deepcopy(record["scene"])
            for declaration in scene["entities"].values():
                declaration["value"] = None
                declaration.pop("origin", None)
            pattern = dumps(scene)
            counts[pattern] += 1
            support.setdefault(pattern, []).append(key)
        return [{"pattern": json.loads(p), "count": n, "support": support[p], "status": "candidate"}
                for p, n in sorted(counts.items()) if n >= 2]

    def snapshot(self):
        return {"version": 1, "concepts": catalog_data(self.concepts),
                "contexts": deepcopy(self.contexts), "records": deepcopy(self.records)}

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = dumps(self.snapshot()) + "\n"
        if len(data.encode("utf-8")) > 100 * 1024 * 1024:
            raise Invalid("Исчерпан бюджет файла")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(data, encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 100 * 1024 * 1024:
            raise Invalid("Исчерпан бюджет файла")
        data = json.loads(path.read_text(encoding="utf-8"))
        memory = cls()
        if not isinstance(data, dict) or set(data) != {"version", "concepts", "contexts", "records"}:
            raise Invalid("Недопустимый snapshot")
        if data["version"] != 1 or data["concepts"] != json.loads(dumps(catalog_data(memory.concepts))):
            raise Invalid("Неподдерживаемый формат/каталог")
        if not isinstance(data["contexts"], dict) or not isinstance(data["records"], dict):
            raise Invalid("Контексты/записи должны быть объектами")
        if len(data["contexts"]) > 1000 or len(data["records"]) > 1000:
            raise Invalid("Исчерпан бюджет snapshot")
        for context in data["contexts"].values():
            if not isinstance(context, dict) or set(context) != {"parent", "mode"}:
                raise Invalid("Недопустимая форма контекста")
            if context["parent"] is not None and not isinstance(context["parent"], str):
                raise Invalid("Недопустимый адрес родителя")
        for record in data["records"].values():
            if not isinstance(record, dict) or set(record) != {"context", "scene", "provenance", "status", "kind", "split"}:
                raise Invalid("Недопустимая форма записи")
            validate(record["scene"], memory.concepts)
        # Канонический JSON сортирует ключи: порядок родителей и origin восстанавливается явно.
        pending = dict(data["contexts"])
        while pending:
            ready = [k for k, v in pending.items() if v["parent"] is None or v["parent"] in memory.contexts]
            if not ready:
                raise Invalid("Цикл/отсутствующий родитель контекста")
            for key in ready:
                memory.context(key, **pending.pop(key))
        pending = dict(data["records"])
        while pending:
            ready = [k for k, v in pending.items() if all("origin" not in e or e["origin"].split(":")[0] in memory.records
                                                        for e in v["scene"]["entities"].values())]
            if not ready:
                raise Invalid("Цикл/отсутствующий origin")
            for key in ready:
                record = pending.pop(key)
                memory.add(key, **record)
        return memory


def evidence(text, language="formal", source="авторский контроль v1", interpretation="authored"):
    return [{"source": source, "language": language, "text": text, "interpretation": interpretation}]
