from neuroliq.autonomous.language import parse
from neuroliq.autonomous.memory import Memory, evidence
from neuroliq.autonomous.navigation import Budget, Navigator, Query
from neuroliq.autonomous.representation import apply, cid, entity, ref, signature


def memory():
    result = Memory()
    result.context("story")
    result.context("chapter", "story")
    result.context("belief_area", "story", "belief")
    sources = {
        "positive": "Мария дала книгу Игорю.",
        "negative": "Мария не дала книгу Игорю.",
        "possible": "Возможно, что Мария дала книгу Игорю.",
        "embedded": "Анна думает, что Мария дала книгу Игорю.",
        "unknown": "Мария дала книгу неизвестному.",
    }
    for key, text in sources.items():
        result.add(key, "chapter", parse(text, "ru"), evidence(text, "ru"))
    result.add("abstract", "chapter", parse(sources["positive"], "ru"), evidence("Схема"), kind="abstract")
    result.add("not_fact_area", "belief_area", parse(sources["positive"], "ru"), evidence("Убеждение"))
    result.add("proposed", "chapter", parse(sources["positive"], "ru"), evidence("Предложение"), status="proposed")
    return result


def test_baseline_scope_context_and_unknown():
    navigator = Navigator(memory())
    query = Query("story", cid("give"), {2: {"value": "Игорь"}}, descendants=True)
    fixed, scan = navigator.search(query), navigator.search(query, full_scan=True)
    assert fixed["complete"] and scan["complete"]
    assert {r["event"] for r in fixed["results"]} == {r["event"] for r in scan["results"]} == {"positive#0"}
    assert fixed["cost"]["visits"] < scan["cost"]["visits"]
    assert navigator.search(Query("story", cid("give")))["status"] == "no_data"
    assert signature(fixed["results"][0]["scene"]) == signature(parse("Мария дала книгу Игорю.", "ru"))
    negative = navigator.search(Query("chapter", cid("give"), wrappers=(cid("past"), cid("not"))))
    assert {r["event"] for r in negative["results"]} == {"negative#0/0"}
    embedded = navigator.search(Query("chapter", cid("give"), wrappers=(cid("think"), cid("past"))))
    assert embedded["results"][0]["embedded"]
    assert embedded["results"][0]["scene"]["root"]["concept"] == cid("think")


def test_resource_refusal_and_context_mode():
    navigator = Navigator(memory())
    query = Query("story", cid("give"), descendants=True)
    result = navigator.search(query, Budget(visits=1))
    assert result["status"] == "budget_exhausted" and not result["complete"]
    result = navigator.search(query, Budget(depth=1))
    assert result["reason"] == "depth"
    explicit = navigator.search(Query("belief_area", cid("give"), modes=("belief",)))
    assert len(explicit["results"]) == 1


def test_extract_one_event_from_joint_scene():
    data = Memory()
    data.context("scene")
    entities = {"a": entity("human", "Мария"), "b": entity("human", "Игорь"), "k": entity("book")}
    data.add("both", "scene", {"entities": entities, "root": apply("all", apply("past", apply("give", ref("a"), ref("k"), ref("b"))), apply("past", apply("see", ref("a"), ref("b"))))}, evidence("Два события"))
    result = Navigator(data).search(Query("scene", cid("give")))
    assert len(result["results"]) == 1
    assert result["results"][0]["scene"]["root"]["concept"] == cid("past")
