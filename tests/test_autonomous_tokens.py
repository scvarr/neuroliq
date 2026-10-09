import json
import pytest
from neuroliq.autonomous.language import parse
from neuroliq.autonomous.learning import corpus
from neuroliq.autonomous.memory import Memory, evidence
from neuroliq.autonomous.representation import Invalid, entity, signature
from neuroliq.autonomous.tokens import BYTE_BASE, Codec, export, meaning


def test_unicode_types_concepts_and_alpha_tokens():
    codec = Codec()
    payload = {"scene": parse("Мария думает, что Игорь дал ключ Анне.", "ru"),
               "values": ["漢字 🧠", 42, -0.25, None, False, True]}
    tokens = codec.encode(payload)
    assert codec.decode(tokens) == payload
    assert codec.encode(codec.decode(tokens)) == tokens
    assert signature(payload["scene"]) == signature(codec.decode(tokens)["scene"])


@pytest.mark.parametrize("tokens", [[0], [0, 99999], [0, 9, 9], [0, 5, BYTE_BASE + 255, 6], [0, 7, BYTE_BASE + ord('t'), 8], [False, 9]])
def test_malformed_stream(tokens):
    with pytest.raises(Invalid):
        Codec().decode(tokens)


def test_export_preserves_context_origins_and_split(tmp_path):
    memory = Memory()
    memory.context("world")
    memory.context("nested", "world")
    memory.add("a", "world", parse("Мария дала книгу Игорю.", "ru"), evidence("Источник", "ru"), split="train")
    memory.add("b", "nested", parse("Она дала ключ Анне.", "ru", {"она": entity("human", "Мария", "a:r0")}), evidence("Продолжение", "ru", interpretation="resolved"), split="test")
    payload = meaning(memory, "b")
    assert payload["references"]["a:r0"]["entity"]["value"] == "Мария"
    assert set(payload["contexts"]) == {"world", "nested"}
    summary = export(memory, tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["splits"] == {"train": 1, "validation": 0, "test": 1}
    assert all(Codec().decode(row["tokens"]) == row["meaning"] for row in rows)
