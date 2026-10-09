"""Один цикл обучения стоимости структурного входа, без изменения содержания."""

from dataclasses import asdict
from statistics import mean
from time import perf_counter

from .memory import Memory, evidence
from .navigation import Navigator, Query
from .representation import apply, cid, entity, ref

NAMES = ("Мария", "Игорь", "Анна", "Олег", "Елена", "Борис")
SEED = 101  # Генерация арифметическая: seed — версия детерминированного смещения.


def dimension(feature):
    return "predicate" if feature[0] == "predicate" else f"role:{feature[1]}:{feature[2]}"


class Policy:
    def __init__(self):
        self.estimates = {}
        self.samples = {}
        self.probe_visits = 0

    def choose(self, features):
        return min(features, key=lambda f: self.estimates.get(dimension(f), 1.0))

    def fit(self, navigator, queries):
        started = perf_counter()
        for query in queries:
            navigator.validate_query(query)
            for feature in navigator.features(query):
                # Сигнал получен реально пройденными train-вхождениями, без доступа к test.
                visits = sum(1 for _ in navigator.postings.get(feature, []))
                self.probe_visits += visits
                key = dimension(feature)
                cost = visits / max(1, len(navigator.events))
                n = self.samples.get(key, 0) + 1
                old = self.estimates.get(key, 0.0)
                self.estimates[key] = old + (cost - old) / n
                self.samples[key] = n
        return {"seconds": perf_counter() - started, "probe_visits": self.probe_visits,
                "parameters": dict(self.estimates), "samples": dict(self.samples), "passes": 1}

    def snapshot(self):
        return {"version": 1, "estimates": dict(self.estimates), "samples": dict(self.samples),
                "probe_visits": self.probe_visits}


def wrappers(index):
    return ((cid("past"),), (cid("past"), cid("not")), (cid("possible"), cid("past")))[index % 3]


def make_transfer(actor, recipient, item, outer):
    scene = {"entities": {"a": entity("human", actor), "k": entity(item), "b": entity("human", recipient)},
             "root": apply("give", ref("a"), ref("k"), ref("b"))}
    for modifier in reversed(outer):
        scene["root"] = {"concept": modifier, "args": [scene["root"]]}
    return scene


def corpus(split, noise=4, shifted=False):
    memory, tasks = Memory(), []
    offset = {"train": 1, "validation": 3, "test": 2}[split]
    for index, actor in enumerate(NAMES):
        context = f"{split}-scene-{index}"
        memory.context(context)
        recipient = NAMES[(index + offset) % len(NAMES)]
        outer = wrappers(index + offset)
        item = ("book", "key")[(index + offset + SEED) % 2]
        record = f"{split}-{index}-target"
        memory.add(record, context, make_transfer(actor, recipient, item, outer),
                   evidence(f"Авторская сцена {actor}/{item}/{recipient}; split={split}; seed={SEED}"), split=split)
        query = Query(context, cid("give"), {0: {"value": actor}}, wrappers=outer)
        event = record + "#" + "/".join("0" for _ in outer)
        tasks.append({"query": query, "gold": {event}, "compound": (actor, recipient, item, outer)})
        for j in range(noise):
            # Противоположное распределение содержит только see: give становится дешёвым входом.
            if not shifted:
                distractor = make_transfer(f"Отвлекающий-{j}", f"Другой-{j}", "book", (cid("past"),))
                memory.add(f"{split}-{index}-give-{j}", context, distractor, evidence("Структурное отвлекающее событие"), split=split)
            seen_actor = NAMES[(j + index + SEED) % len(NAMES)]
            scene = {"entities": {"a": entity("human", seen_actor), "b": entity("human", f"Другой-{j}")},
                     "root": apply("past", apply("see", ref("a"), ref("b")))}
            memory.add(f"{split}-{index}-see-{j}", context, scene, evidence("Отвлекающее наблюдение"), split=split)
    return memory, tasks


def evaluate(navigator, tasks, policy=None, full_scan=False):
    visits, seconds, steps, outcomes, failures = [], [], [], [], []
    for task in tasks:
        result = navigator.search(task["query"], policy=policy, full_scan=full_scan)
        actual = {r["event"] for r in result["results"]}
        correct = result["complete"] and actual == task["gold"]
        outcomes.append(correct)
        visits.append(result["cost"]["visits"])
        steps.append(result["cost"]["steps"])
        seconds.append(result["cost"]["seconds"])
        if not correct:
            failures.append({"query": asdict(task["query"]), "gold": sorted(task["gold"]),
                             "actual": sorted(actual), "status": result["status"]})
    return {"queries": len(tasks), "exact_set_accuracy": mean(outcomes), "mean_visits": mean(visits),
            "mean_steps": mean(steps), "mean_seconds": mean(seconds), "total_visits": sum(visits), "failures": failures}


def experiment():
    training_memory, training_tasks = corpus("train")
    training = Navigator(training_memory)
    policy = Policy()
    before = policy.snapshot()
    learning = policy.fit(training, [task["query"] for task in training_tasks])
    validation_memory, validation_tasks = corpus("validation")
    validation_nav = Navigator(validation_memory)
    validation = {"fixed": evaluate(validation_nav, validation_tasks), "learned": evaluate(validation_nav, validation_tasks, policy)}
    measurements, seen_test_compounds = [], set()
    training_compounds = {task["compound"] for task in training_tasks}
    validation_compounds = {task["compound"] for task in validation_tasks}
    for noise in (0, 8, 40):
        memory, tasks = corpus("test", noise)
        navigator = Navigator(memory)
        test_compounds = {task["compound"] for task in tasks}
        assert not test_compounds & (training_compounds | validation_compounds)
        seen_test_compounds |= test_compounds
        fixed, learned = evaluate(navigator, tasks), evaluate(navigator, tasks, policy)
        measurements.append({"noise_per_scene": noise, "records": len(memory.records), "build_nodes": navigator.build_nodes,
                             "build_seconds": navigator.build_seconds, "posting_entries": sum(map(len, navigator.postings.values())),
                             "fixed": fixed, "learned": learned, "full_scan": evaluate(navigator, tasks, full_scan=True),
                             "visit_reduction": 1 - learned["mean_visits"] / fixed["mean_visits"]})
    shifted_memory, shifted_tasks = corpus("test", 40, shifted=True)
    shifted = Navigator(shifted_memory)
    return {"version": 1, "seed": SEED, "before": before, "learning": learning, "after": policy.snapshot(),
            "validation": validation, "measurements": measurements,
            "distribution_shift": {"fixed": evaluate(shifted, shifted_tasks), "learned": evaluate(shifted, shifted_tasks, policy)},
            "split_check": {"train_targets": len(training_compounds), "validation_targets": len(validation_compounds),
                            "test_targets": len(seen_test_compounds), "target_compound_overlap": 0},
            "claim": "Обучение только порядка структурного входа; не смысловая индукция и не логическое рассуждение"}


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from .representation import dumps
    parser = argparse.ArgumentParser(description="Один ограниченный цикл адаптации навигации")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(experiment()) + "\n", encoding="utf-8")
