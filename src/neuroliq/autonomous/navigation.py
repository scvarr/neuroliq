"""Наблюдаемый обход структурных вхождений с конечными бюджетами."""

from dataclasses import dataclass, field
from time import perf_counter

from .representation import Invalid, canonical, cid, ref

UNARY = {cid(key) for key in ("past", "not", "possible")}


@dataclass(frozen=True)
class Query:
    context: str
    predicate: str
    roles: dict[int, dict] = field(default_factory=dict)
    wrappers: tuple[str, ...] = (cid("past"),)
    descendants: bool = False
    kind: str = "observation"
    status: str = "accepted"
    modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Budget:
    visits: int = 1000
    depth: int = 16
    seconds: float = 1.0

    def validate(self):
        if not 0 <= self.visits <= 1000 or not 1 <= self.depth <= 16 or not 0 <= self.seconds <= 1.0:
            raise Invalid("Недопустимый бюджет навигации")


class Navigator:
    def __init__(self, memory):
        self.memory = memory
        self.events, self.postings = {}, {}
        started = perf_counter()
        self.build_nodes = 0
        for record_id, record in sorted(memory.records.items()):
            def walk(term, path=(), wrappers=()):
                self.build_nodes += 1
                if "concept" not in term:
                    return
                concept = term["concept"]
                if concept == cid("all"):
                    next_wrappers = wrappers
                elif concept in UNARY:
                    next_wrappers = wrappers + (concept,)
                else:
                    key = record_id + "#" + "/".join(map(str, path))
                    event = {"record": record_id, "path": path, "term": term, "wrappers": wrappers}
                    self.events[key] = event
                    self._post(("predicate", concept), key)
                    for position, arg in enumerate(term["args"]):
                        if "ref" in arg:
                            declaration = record["scene"]["entities"][arg["ref"]]
                            for attribute in ("concept", "value", "origin"):
                                if declaration.get(attribute) is not None:
                                    self._post(("role", position, attribute, declaration[attribute]), key)
                    next_wrappers = wrappers + (concept,)
                for position, arg in enumerate(term["args"]):
                    walk(arg, path + (position,), next_wrappers)
            walk(record["scene"]["root"])
        self.build_seconds = perf_counter() - started

    def _post(self, feature, key):
        self.postings.setdefault(feature, []).append(key)

    def features(self, query):
        result = [("predicate", query.predicate)]
        for position, constraints in sorted(query.roles.items()):
            for attribute, value in sorted(constraints.items()):
                if value is not None:
                    result.append(("role", position, attribute, value))
        return result

    def validate_query(self, query):
        self.memory.visible(query.context, query.descendants)
        concept = self.memory.concepts.get(query.predicate)
        if concept is None or concept.result != "proposition":
            raise Invalid("Неизвестный предикат запроса")
        if query.kind not in ("observation", "abstract") or query.status not in ("accepted", "proposed"):
            raise Invalid("Недопустимый статус запроса")
        for position, constraints in query.roles.items():
            if type(position) is not int or position < 0 or position >= len(concept.positions):
                raise Invalid("Недопустимая позиция запроса")
            if not constraints or not set(constraints) <= {"concept", "value", "origin"}:
                raise Invalid("Недопустимые ограничения роли")
            for value in constraints.values():
                if value is None or type(value) not in (str, int, float, bool):
                    raise Invalid("Неизвестное значение не является селектором факта")

    def _modes(self, context):
        modes = set()
        while context is not None:
            data = self.memory.contexts[context]
            if data["mode"] != "source":
                modes.add(data["mode"])
            context = data["parent"]
        return modes

    def _match(self, event, query, contexts):
        record = self.memory.records[event["record"]]
        if record["context"] not in contexts:
            return "context"
        if self._modes(record["context"]) != set(query.modes):
            return "context_mode"
        if record["kind"] != query.kind or record["status"] != query.status:
            return "record_status"
        if event["wrappers"] != query.wrappers:
            return "scope"
        if event["term"]["concept"] != query.predicate:
            return "predicate"
        for position, constraints in query.roles.items():
            args = event["term"]["args"]
            if position >= len(args) or "ref" not in args[position]:
                return "unknown_role"
            declaration = record["scene"]["entities"][args[position]["ref"]]
            if any(declaration.get(attribute) != value for attribute, value in constraints.items()):
                return "role"
        return "match"

    def _answer(self, event):
        record = self.memory.records[event["record"]]
        root = event["term"]
        # Нельзя отрезать владельца убеждения или условие от вложенного содержания.
        embedded = any(wrapper not in UNARY for wrapper in event["wrappers"])
        if embedded:
            root = record["scene"]["root"]
        else:
            for wrapper in reversed(event["wrappers"]):
                root = {"concept": wrapper, "args": [root]}
        used = set()

        def refs(term):
            if "ref" in term:
                used.add(term["ref"])
            for arg in term.get("args", []):
                refs(arg)
        refs(root)
        scene = canonical({"entities": {key: record["scene"]["entities"][key] for key in used}, "root": root})
        return {"scene": scene, "context": record["context"], "provenance": record["provenance"],
                "status": record["status"], "kind": record["kind"], "embedded": embedded,
                "focus_path": list(event["path"])}

    def search(self, query, budget=None, full_scan=False, policy=None):
        self.validate_query(query)
        budget = Budget() if budget is None else budget
        budget.validate()
        started = perf_counter()
        contexts = self.memory.visible(query.context, query.descendants)
        features = self.features(query)
        selected = features[0] if policy is None else policy.choose(features)
        candidates = list(self.events) if full_scan else self.postings.get(selected, [])
        results, trace = [], []
        complete, reason, steps = True, None, 0
        for key in candidates:
            if len(trace) >= budget.visits or perf_counter() - started >= budget.seconds:
                complete, reason = False, "visits_or_time"
                break
            event = self.events[key]
            if len(event["path"]) + 1 > budget.depth:
                complete, reason = False, "depth"
                break
            decision = self._match(event, query, contexts)
            steps += len(event["path"]) + 1
            trace.append({"event": key, "decision": decision, "path": list(event["path"])})
            if decision == "match":
                results.append({"event": key, **self._answer(event)})
        return {"status": ("ok" if results else "no_data") if complete else "budget_exhausted",
                "complete": complete, "reason": reason, "results": results, "trace": trace,
                "cost": {"visits": len(trace), "steps": steps, "seconds": perf_counter() - started,
                         "entry": list(selected) if not full_scan else ["full_scan"],
                         "posting_reads": 0 if full_scan else 1}}
