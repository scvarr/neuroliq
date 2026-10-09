import json
import pytest
from neuroliq.autonomous.memory import Memory, evidence
from neuroliq.autonomous.representation import Invalid, apply, entity, ref


def scene(name="Мария", origin=None):
    return {"entities": {"a": entity("human", name, origin), "b": entity("human", "Игорь")},
            "root": apply("see", ref("a"), ref("b"))}


def test_shared_basis_context_and_persistence(tmp_path):
    memory = Memory()
    memory.context("world")
    memory.context("chapter", "world")
    memory.context("belief", "chapter", "belief")
    memory.add("first", "chapter", scene(), evidence("Мария увидела Игоря.", "ru"), split="train")
    memory.add("next", "chapter", scene(origin="first:r0"), evidence("Она увидела Игоря.", "ru", interpretation="resolved"), split="train")
    memory.add("thought", "belief", scene("Анна"), evidence("Содержание убеждения"))
    memory.context("schema", mode="abstract")
    memory.add("schema1", "schema", scene(None), evidence("Общая конструкция"), kind="abstract")
    assert len(memory.concepts) == 11
    assert memory.visible("world") == {"world"}
    assert memory.visible("world", True) == {"world", "chapter", "belief"}
    assert memory.patterns()[0]["count"] == 2
    path = tmp_path / "memory.json"
    memory.save(path)
    assert Memory.load(path).snapshot() == memory.snapshot()


def test_mismatched_origin_ambiguity_and_cycles(tmp_path):
    memory = Memory()
    memory.context("root")
    memory.add("first", "root", scene(), evidence("Первое наблюдение"))
    with pytest.raises(Invalid, match="Origin"):
        memory.add("wrong", "root", scene("Анна", "first:r0"), evidence("Ошибка"))
    with pytest.raises(Invalid, match="Неоднозначная"):
        memory.add("ambiguous", "root", scene(), evidence("Она", interpretation="ambiguous"))
    snapshot = memory.snapshot()
    snapshot["contexts"]["root"]["parent"] = "root"
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(Invalid, match="Цикл"):
        Memory.load(path)
