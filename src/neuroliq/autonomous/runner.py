"""P9: воспроизводимый сквозной срез и честная фиксация границ результата."""

from collections import defaultdict
from dataclasses import asdict
import ctypes
import importlib.metadata
import os
from pathlib import Path
import platform
from time import perf_counter, process_time

from .comparison import compare
from .fixtures import cases, transfer
from .language import Unsupported, parse, render
from .learning import Policy, corpus, experiment
from .memory import Memory, evidence
from .navigation import Budget, Navigator, Query
from .representation import Invalid, apply, canonical, cid, dumps, entity, ref, signature
from .tokens import Codec, export, export_targets, meaning


def peak_rss():
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (key, ctypes.c_size_t) for key in ("peak", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise Invalid("Не удалось измерить RSS")
        return counters.peak
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if platform.system() == "Darwin" else rss * 1024


class Limits:
    def __init__(self):
        self.wall = perf_counter()
        self.cpu = process_time()

    def check(self):
        result = {"wall_seconds": perf_counter() - self.wall, "cpu_seconds": process_time() - self.cpu,
                  "peak_rss_bytes": peak_rss(), "gpu_seconds": 0, "download_bytes": 0}
        if result["wall_seconds"] > 60 or result["cpu_seconds"] > 1800 or result["peak_rss_bytes"] > 512 * 1024 * 1024:
            raise Invalid("Исчерпан абсолютный ресурсный лимит стенда")
        return result


def demo(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    memory, groups = Memory(), defaultdict(lambda: {"passed": 0, "total": 0, "failures": []})
    memory.context("source")
    memory.context("chapter", "source")
    memory.context("abstract", mode="abstract")
    memory.context("belief_area", "source", "belief")

    def check(group, condition, detail):
        groups[group]["total"] += 1
        if condition:
            groups[group]["passed"] += 1
        else:
            groups[group]["failures"].append(detail)

    for group, key, ru, en, gold in cases():
        parsed = [parse(ru, "ru"), parse(en, "en")]
        for language, scene in zip(("ru", "en"), parsed):
            check(group, signature(scene) == signature(gold), {"case": key, "language": language})
            check("language_roundtrip", signature(parse(render(scene, language), language)) == signature(gold), key)
        sources = evidence(ru, "ru") + evidence(en, "en")
        memory.add(key, "chapter", parsed[0], sources, split="test")
    continuation = parse("Она дала ключ Анне.", "ru", {"она": entity("human", "Мария", "positive:r0")})
    explicit_gold = transfer("Мария", "Анна", "key")
    explicit_gold["entities"]["a"]["origin"] = "positive:r0"
    check("coreference", signature(continuation) == signature(explicit_gold), "Явное разрешение местоимения")
    memory.add("continued", "chapter", continuation, evidence("Она дала ключ Анне.", "ru", interpretation="resolved"))
    abstract = transfer(None, None)
    abstract["root"] = abstract["root"]["args"][0]
    memory.add("schema", "abstract", abstract, evidence("Общая схема, не событие"), kind="abstract")
    memory.add("context_belief", "belief_area", transfer(), evidence("Содержание убеждения в отдельной области"))
    memory.add("ambiguous", "chapter", transfer(), evidence("Она дала книгу Игорю.", "ru", interpretation="ambiguous"), status="proposed")
    same_name = {"entities": {"a": entity("human", "Мария"), "b": entity("human", "Мария")}, "root": apply("past", apply("see", ref("a"), ref("b")))}
    memory.add("same_name", "chapter", same_name, evidence("Два разных участника с одинаковым именем, ручная разметка"))
    joint = transfer()
    joint["root"] = apply("all", joint["root"], apply("past", apply("see", ref("a"), ref("b"))))
    memory.add("joint", "chapter", joint, evidence("Мария дала книгу Игорю и увидела его; два события с общими участниками"))
    check("same_name", signature(same_name) != signature({"entities": {"a": entity("human", "Мария")}, "root": apply("past", apply("see", ref("a"), ref("a")))}), "Разные одноимённые участники")
    memory.save(directory / "memory.json")
    restored = Memory.load(directory / "memory.json")
    check("persistence", restored.snapshot() == memory.snapshot(), "Snapshot round-trip")
    navigator = Navigator(restored)
    query = Query("source", cid("give"), {0: {"value": "Мария"}, 2: {"value": "Игорь"}}, descendants=True)
    result = navigator.search(query)
    baseline = navigator.search(query, full_scan=True)
    gold_events = {"positive#0", "received#0", "joint#0/0"}
    check("navigation", {r["event"] for r in result["results"]} == gold_events, "Не должно быть belief/possible/unknown/abstract/proposed")
    check("navigation", {r["event"] for r in baseline["results"]} == gold_events, "Полный baseline")
    check("context", navigator.search(Query("source", cid("give")))["status"] == "no_data", "Descendants только явно")
    check("context", len(navigator.search(Query("abstract", cid("give"), wrappers=(), kind="abstract", modes=("abstract",)))["results"]) == 1, "Схема извлекается только явно")
    failure = navigator.search(query, Budget(visits=1))
    check("budget", failure["status"] == "budget_exhausted" and not failure["complete"], "Ограничение посещений")
    codec = Codec()
    for key in memory.records:
        payload = meaning(memory, key)
        check("token_roundtrip", codec.decode(codec.encode(payload)) == payload, key)
    expressions = [{"event": r["event"], "ru": render(r["scene"], "ru"), "en": render(r["scene"], "en")} for r in result["results"]]
    refusals = []
    for text, language, property_name in [
        ("Она дала книгу Игорю.", "ru", "неразрешённое местоимение"),
        ("Мария увидела Марию.", "ru", "одноимённость без identity"),
        ("Maria was giving a book to Igor.", "en", "progressive aspect"),
        ("У каждой книги есть автор.", "ru", "квантификация"),
    ]:
        try:
            parse(text, language)
            check("explicit_refusal", False, property_name)
        except Unsupported as error:
            check("explicit_refusal", True, property_name)
            refusals.append({"text": text, "language": language, "property": property_name, "reason": str(error)})
    python_source = "x = 0\nif x == 0:\n    x = 1\n"
    # Ожидаемый переход задан вручную, встроенный Python interpreter/eval не используется как ядро.
    python_probe = {"source": python_source, "expected_transition": {"before": {"x": 0}, "after": {"x": 1}},
                    "supported": False, "reason": "v1 не содержит binding переменной, численного равенства и обновления состояния; IF для содержаний не выполняет присваивание"}
    attempted = {"entities": {}, "root": apply("assign", {"literal": "x"}, {"literal": 0})}
    try:
        canonical(attempted)
        check("python_boundary", False, "Неизвестный assign не должен приниматься")
    except Invalid as error:
        python_probe["construction_refusal"] = str(error)
        check("python_boundary", True, "Реальный отказ неподдерживаемого assign")
    check("python_boundary", python_probe["supported"] is False, "Явный отрицательный перенос")
    exported = export(restored, directory / "export")
    report = {"groups": dict(groups), "records": len(memory.records), "concepts": len(memory.concepts),
              "query": asdict(query), "navigation": result, "baseline": baseline, "failure_trace": failure,
              "expressions": expressions, "refusals": refusals, "python_probe": python_probe,
              "export": exported, "scheme_candidates": restored.patterns(split="test")}
    (directory / "query.json").write_text(dumps(asdict(query)) + "\n", encoding="utf-8")
    (directory / "report.json").write_text(dumps(report) + "\n", encoding="utf-8")
    return report


def run(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    limits = Limits()
    report = demo(directory / "demo")
    limits.check()
    learning = experiment()
    limits.check()
    exported = export_targets(directory / "export")
    limits.check()
    (directory / "learning.json").write_text(dumps(learning) + "\n", encoding="utf-8")
    (directory / "comparison.json").write_text(dumps(compare()) + "\n", encoding="utf-8")
    versions = {package: importlib.metadata.version(package) for package in ("pydantic", "pytest", "setuptools")}
    resource = limits.check()
    resource["artifact_bytes"] = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
    if resource["artifact_bytes"] > 100 * 1024 * 1024:
        raise Invalid("Исчерпан бюджет артефактов")
    successful = all(group["passed"] == group["total"] for group in report["groups"].values())
    summary = {"version": 1, "bounded_validation_passed": successful,
               "central_hypothesis_confirmed": False,
               "result": "Ограниченные механизмы проверены; автоматическое выращивание универсальной смысловой основы не подтверждено",
               "completed_stages": [f"P{i}" for i in range(10)], "resources": resource,
               "environment": {"python": platform.python_version(), "platform": platform.platform(), "versions": versions},
               "groups": report["groups"], "learning": learning["measurements"][-1],
               "distribution_shift": learning["distribution_shift"], "export": exported,
               "python_transfer_supported": False,
               "stop_condition": "Контракт 12.4.1/4: конечный срез выполнен, независимых данных для главной гипотезы нет; расширение не требуется"}
    (directory / "summary.json").write_text(dumps(summary) + "\n", encoding="utf-8")
    if not successful:
        raise Invalid("Финальная групповая проверка обнаружила ошибку; см. report.json")
    return summary
