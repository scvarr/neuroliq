"""Ограниченная композиция, проверка ссылок и alpha-канонизация."""

from dataclasses import asdict, dataclass
import json
from math import isfinite
from uuid import UUID, uuid5

NAMESPACE = UUID("bb3b1ebe-c9e5-4ccc-9dd6-3f40c847b4d2")
MAX_DEPTH = 16
MAX_NODES = 256


class Invalid(ValueError):
    """Диагностируемая недопустимая конструкция."""


@dataclass(frozen=True)
class Concept:
    id: str
    annotation: str
    result: str
    positions: tuple[str, ...] = ()
    variadic: bool = False


def cid(key):
    return str(uuid5(NAMESPACE, key))


def catalog():
    # Аннотации читаются адаптером; ядро использует адрес и контракт позиций.
    specs = {
        "human": ("человек", "human", ()),
        "book": ("книга", "item", ()),
        "key": ("ключ", "item", ()),
        "give": ("передача: передающий, предмет, получатель", "proposition", ("human", "item", "human")),
        "see": ("наблюдение: наблюдатель, наблюдаемый", "proposition", ("human", "human")),
        "think": ("убеждение: носитель, содержание", "proposition", ("human", "proposition")),
        "not": ("отрицание содержания", "proposition", ("proposition",)),
        "past": ("прошлое содержания", "proposition", ("proposition",)),
        "possible": ("возможность содержания", "proposition", ("proposition",)),
        "if": ("условие и следствие, без утверждения частей", "proposition", ("proposition", "proposition")),
        "all": ("совместные содержания; порядок записи не есть время", "proposition", ("proposition",)),
    }
    return {cid(k): Concept(cid(k), text, result, positions, k == "all")
            for k, (text, result, positions) in specs.items()}


def ref(key):
    return {"ref": key}


def unknown():
    return {"unknown": True}


def apply(key, *args):
    return {"concept": cid(key), "args": list(args)}


def entity(key, value=None, origin=None):
    result = {"concept": cid(key), "value": value}
    if origin is not None:
        result["origin"] = origin
    return result


def scalar(value):
    if type(value) not in (str, int, float, bool, type(None)):
        raise Invalid("Ожидалось скалярное конкретное значение")
    if isinstance(value, float) and not isfinite(value):
        raise Invalid("Бесконечные значения запрещены")
    if isinstance(value, str) and len(value) > 4096:
        raise Invalid("Слишком длинное значение")


def validate(scene, concepts=None):
    concepts = catalog() if concepts is None else concepts
    if not isinstance(scene, dict) or set(scene) != {"entities", "root"}:
        raise Invalid("Конструкция должна содержать только entities и root")
    entities = scene["entities"]
    if not isinstance(entities, dict) or len(entities) > MAX_NODES:
        raise Invalid("Недопустимые объявления участников")
    for key, data in entities.items():
        if not isinstance(key, str) or not key or len(key) > 256:
            raise Invalid("Недопустимый адрес участника")
        if not isinstance(data, dict) or set(data) not in ({"concept", "value"}, {"concept", "value", "origin"}):
            raise Invalid("Недопустимое объявление участника")
        concept = concepts.get(data["concept"])
        if concept is None or concept.positions or concept.result == "proposition":
            raise Invalid("Неизвестный или не предметный концепт участника")
        scalar(data["value"])
        if "origin" in data and (not isinstance(data["origin"], str) or not data["origin"]):
            raise Invalid("Недопустимая внешняя ссылка")
    used, count = set(), 0

    def visit(term, depth):
        nonlocal count
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise Invalid("Исчерпан бюджет глубины/узлов композиции")
        if not isinstance(term, dict):
            raise Invalid("Узел должен быть объектом")
        if set(term) == {"unknown"} and term["unknown"] is True:
            return "unknown"
        if set(term) == {"ref"}:
            key = term["ref"]
            if not isinstance(key, str) or key not in entities:
                raise Invalid("Ссылка не имеет объявления")
            used.add(key)
            return concepts[entities[key]["concept"]].result
        if set(term) != {"concept", "args"} or not isinstance(term["args"], list):
            raise Invalid("Недопустимое применение")
        concept = concepts.get(term["concept"])
        if concept is None or not concept.positions:
            raise Invalid("Неизвестный или неприменимый концепт")
        args = term["args"]
        if (concept.variadic and not args) or (not concept.variadic and len(args) != len(concept.positions)):
            raise Invalid("Неверное число позиций")
        for index, arg in enumerate(args):
            expected = concept.positions[0 if concept.variadic else index]
            actual = visit(arg, depth + 1)
            if actual not in (expected, "unknown"):
                raise Invalid(f"Несовместимый аргумент в позиции {index}: {actual}, ожидался {expected}")
        return concept.result

    if visit(scene["root"], 1) != "proposition":
        raise Invalid("Корень должен выражать содержание")
    if used != set(entities):
        raise Invalid("Есть неиспользованные объявления")


def canonical(scene, concepts=None):
    validate(scene, concepts)
    mapping, declarations = {}, {}

    def visit(term):
        if "ref" in term:
            old = term["ref"]
            if old not in mapping:
                new = f"r{len(mapping)}"
                mapping[old] = new
                declarations[new] = dict(scene["entities"][old])
            return ref(mapping[old])
        if "unknown" in term:
            return unknown()
        return {"concept": term["concept"], "args": [visit(arg) for arg in term["args"]]}

    root = visit(scene["root"])
    return {"entities": declarations, "root": root}


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def signature(scene, concepts=None):
    return dumps(canonical(scene, concepts))


def catalog_data(concepts):
    return {key: asdict(value) for key, value in sorted(concepts.items())}
