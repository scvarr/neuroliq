"""Канонический обратимый токенный формат с byte values и стабильными ConceptId."""

import json
from pathlib import Path

from .representation import Invalid, canonical, catalog, dumps, scalar

RESERVED = ("NEUROLIQ_V1", "OBJECT", "END_OBJECT", "ARRAY", "END_ARRAY", "STRING", "END_STRING",
            "NUMBER", "END_NUMBER", "NULL", "TRUE", "FALSE")
BYTE_BASE = 32
CONCEPT_BASE = BYTE_BASE + 256
MAX_TOKENS = 65536


class Codec:
    def __init__(self):
        self.concepts = sorted(catalog())
        self.concept_tokens = {key: CONCEPT_BASE + i for i, key in enumerate(self.concepts)}

    def vocabulary(self):
        return {"version": 1, "reserved": {str(i): token for i, token in enumerate(RESERVED)},
                "bytes": {str(BYTE_BASE + i): i for i in range(256)},
                "concepts": {str(token): concept for concept, token in self.concept_tokens.items()},
                "max_tokens": MAX_TOKENS, "concept_order": "UUID lexical v1, каталог фиксирован"}

    def encode(self, payload):
        stream = [0]

        def emit(value, depth=0):
            if depth > 64:
                raise Invalid("Глубина токенного контейнера исчерпана")
            if isinstance(value, dict):
                if not all(isinstance(key, str) for key in value):
                    raise Invalid("Ключи контейнера должны быть строками")
                stream.append(1)
                for key in sorted(value):
                    emit(key, depth + 1)
                    emit(value[key], depth + 1)
                stream.append(2)
            elif isinstance(value, (list, tuple)):
                stream.append(3)
                for item in value:
                    emit(item, depth + 1)
                stream.append(4)
            elif isinstance(value, str) and value in self.concept_tokens:
                stream.append(self.concept_tokens[value])
            elif isinstance(value, str):
                scalar(value)
                stream.append(5)
                stream.extend(BYTE_BASE + byte for byte in value.encode("utf-8"))
                stream.append(6)
            elif value is None:
                stream.append(9)
            elif type(value) is bool:
                stream.append(10 if value else 11)
            elif type(value) in (int, float):
                scalar(value)
                stream.append(7)
                stream.extend(BYTE_BASE + byte for byte in dumps(value).encode("ascii"))
                stream.append(8)
            else:
                raise Invalid("Неподдерживаемый тип токенного значения")
            if len(stream) > MAX_TOKENS:
                raise Invalid("Бюджет токенов исчерпан")
        emit(payload)
        return stream

    def decode(self, tokens):
        if not isinstance(tokens, list) or not tokens or tokens[0] != 0 or len(tokens) > MAX_TOKENS:
            raise Invalid("Недопустимый токенный frame")
        if not all(type(token) is int for token in tokens):
            raise Invalid("Токены должны быть целыми числами")
        position = 1

        def take():
            nonlocal position
            if position >= len(tokens):
                raise Invalid("Оборванная последовательность")
            token = tokens[position]
            position += 1
            return token

        def read(depth=0):
            if depth > 64:
                raise Invalid("Глубина токенного контейнера исчерпана")
            token = take()
            if token == 1:
                result = {}
                while position < len(tokens) and tokens[position] != 2:
                    key = read(depth + 1)
                    if not isinstance(key, str) or key in result:
                        raise Invalid("Недопустимый/повторный ключ")
                    result[key] = read(depth + 1)
                if take() != 2:
                    raise Invalid("Нет конца объекта")
                return result
            if token == 3:
                result = []
                while position < len(tokens) and tokens[position] != 4:
                    result.append(read(depth + 1))
                if take() != 4:
                    raise Invalid("Нет конца массива")
                return result
            if token in (5, 7):
                ending = 6 if token == 5 else 8
                data = bytearray()
                while position < len(tokens) and tokens[position] != ending:
                    byte = take() - BYTE_BASE
                    if not 0 <= byte <= 255:
                        raise Invalid("Ожидался byte токен")
                    data.append(byte)
                if take() != ending:
                    raise Invalid("Нет конца значения")
                try:
                    value = data.decode("utf-8") if token == 5 else json.loads(data.decode("ascii"))
                except (ValueError, UnicodeError) as error:
                    raise Invalid("Повреждённое значение") from error
                if token == 7 and type(value) not in (int, float):
                    raise Invalid("Ожидалось число")
                scalar(value)
                return value
            if token in (9, 10, 11):
                return {9: None, 10: True, 11: False}[token]
            index = token - CONCEPT_BASE
            if 0 <= index < len(self.concepts):
                return self.concepts[index]
            raise Invalid("Неизвестный структурный токен")

        payload = read()
        if position != len(tokens) or self.encode(payload) != tokens:
            raise Invalid("Неканоническая или лишняя последовательность")
        return payload


def meaning(memory, record_id):
    record = memory.records[record_id]
    contexts, references = {}, {}

    def add_context(key):
        while key is not None:
            contexts[key] = dict(memory.contexts[key])
            key = memory.contexts[key]["parent"]

    def origin(declaration):
        if "origin" not in declaration or declaration["origin"] in references:
            return
        address = declaration["origin"]
        key, local = address.split(":")
        target = memory.records[key]
        referenced = target["scene"]["entities"][local]
        references[address] = {"entity": dict(referenced), "context": target["context"]}
        add_context(target["context"])
        origin(referenced)

    add_context(record["context"])
    for declaration in record["scene"]["entities"].values():
        origin(declaration)
    return {"scene": canonical(record["scene"]), "context": record["context"], "contexts": contexts,
            "references": references, "status": record["status"], "kind": record["kind"]}


def export(memory, directory, record_ids=None):
    from .language import Unsupported, render
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    codec, rows, counts = Codec(), [], {"train": 0, "validation": 0, "test": 0}
    for key in sorted(memory.records if record_ids is None else record_ids):
        record = memory.records[key]
        payload = meaning(memory, key)
        tokens = codec.encode(payload)
        if codec.decode(tokens) != payload:
            raise Invalid("Потеря содержания при экспорте")
        surfaces = {}
        for language in ("ru", "en"):
            try:
                surfaces[language] = render(payload["scene"], language)
            except Unsupported:
                surfaces[language] = None
        rows.append(dumps({"id": key, "split": record["split"], "status": record["status"],
                           "annotation_author": "авторский генератор агента; без независимого human review",
                           "provenance": record["provenance"], "surface_generated": surfaces,
                           "meaning": payload, "tokens": tokens, "vocabulary_version": 1}))
        counts[record["split"]] += 1
    (directory / "vocabulary.json").write_text(dumps(codec.vocabulary()) + "\n", encoding="utf-8")
    (directory / "corpus.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"rows": len(rows), "splits": counts, "roundtrip_failures": 0,
            "vocabulary_version": 1, "transformer_trained": False}


def export_targets(directory):
    from .learning import corpus
    from .memory import Memory
    memory = Memory()
    for split in ("train", "validation", "test"):
        part, _ = corpus(split, noise=0)
        for key, context in part.contexts.items():
            memory.context(key, **context)
        for key, record in part.records.items():
            memory.add(key, **record)
    summary = export(memory, directory)
    memory.save(Path(directory) / "memory.json")
    (Path(directory) / "summary.json").write_text(dumps(summary) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Экспорт внутреннего корпуса без обучения модели")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(dumps(export_targets(args.output)))
