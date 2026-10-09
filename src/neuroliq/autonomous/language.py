"""Внешний детерминированный RU/EN адаптер конечного контролируемого языка."""

import re
from .representation import Invalid, apply, canonical, cid, entity, ref, unknown, validate

NAMES = {
    "Мария": ("Мария", "Марии", "Марию", "Maria"),
    "Игорь": ("Игорь", "Игорю", "Игоря", "Igor"),
    "Анна": ("Анна", "Анне", "Анну", "Anna"),
    "Олег": ("Олег", "Олегу", "Олега", "Oleg"),
    "Елена": ("Елена", "Елене", "Елену", "Elena"),
    "Борис": ("Борис", "Борису", "Бориса", "Boris"),
}
ALIASES = {form.casefold(): name for name, forms in NAMES.items() for form in forms}
ITEMS = {"книгу": "book", "ключ": "key", "a book": "book", "a key": "key"}


class Unsupported(Invalid):
    """Адаптер отказался угадывать неподдерживаемый смысл."""


def parse(text, language, bindings=None):
    if language not in ("ru", "en") or not isinstance(text, str) or len(text) > 4096:
        raise Unsupported("Недопустимый язык/текст")
    bindings = {} if bindings is None else bindings
    declarations, bound_refs, names_seen = {}, {}, set()

    def participant(surface):
        surface = surface.strip().casefold()
        if surface in ("неизвестному", "someone unknown"):
            return unknown()
        if surface in bindings:
            if surface not in bound_refs:
                key = f"p{len(declarations)}"
                declarations[key] = dict(bindings[surface])
                bound_refs[surface] = key
            return ref(bound_refs[surface])
        anonymous = surface in ("человек", "человека", "человеку", "a person")
        name = None if anonymous else ALIASES.get(surface)
        if not anonymous and name is None:
            raise Unsupported(f"Нет однозначного участника: {surface}")
        if name is not None:
            if name in names_seen:
                raise Unsupported("Повторное имя требует явного разрешения coreference")
            names_seen.add(name)
        key = f"p{len(declarations)}"
        declarations[key] = entity("human", name)
        return ref(key)

    def item(surface):
        kind = ITEMS.get(surface.casefold())
        if kind is None:
            raise Unsupported("Предмет вне контролируемого словаря")
        key = f"p{len(declarations)}"
        declarations[key] = entity(kind)
        return ref(key)

    def visit(sentence, depth=1):
        if depth > 12:
            raise Unsupported("Исчерпан бюджет адаптера")
        sentence = sentence.strip().rstrip(".")
        for prefix, operator in (("Возможно, что ", "possible"), ("Possibly, ", "possible"),
                                 ("Неверно, что ", "not"), ("It is false that ", "not")):
            if sentence.casefold().startswith(prefix.casefold()):
                return apply(operator, visit(sentence[len(prefix):], depth + 1))
        for prefix, separator in (("Если ", "; то "), ("If ", "; then ")):
            if sentence.casefold().startswith(prefix.casefold()):
                parts = sentence[len(prefix):].split(separator)
                if len(parts) != 2:
                    raise Unsupported("Условие требует двух однозначных частей")
                return apply("if", *(visit(part, depth + 1) for part in parts))
        match = re.fullmatch(r"(.+?) (?:думает, что|thinks that) (.+)", sentence, re.IGNORECASE)
        if match:
            actor = participant(match[1])
            return apply("think", actor, visit(match[2], depth + 1))
        patterns = [
            (r"(.+?) не (?:дала|дал) (книгу|ключ) (.+)", False, True),
            (r"(.+?) (?:дала|дал) (книгу|ключ) (.+)", False, False),
            (r"(.+?) gave (a book|a key) to (.+)", False, False),
            (r"(.+?) did not give (a book|a key) to (.+)", False, True),
            (r"(.+?) (?:получил|получила) (книгу|ключ) от (.+)", True, False),
            (r"(.+?) received (a book|a key) from (.+)", True, False),
        ]
        for pattern, reverse, negative in patterns:
            match = re.fullmatch(pattern, sentence, re.IGNORECASE)
            if match:
                left, right = (match[3], match[1]) if reverse else (match[1], match[3])
                giver, thing, recipient = participant(left), item(match[2]), participant(right)
                term = apply("give", giver, thing, recipient)
                return apply("past", apply("not", term) if negative else term)
        match = re.fullmatch(r"(.+?) (?:увидел|увидела|saw) (.+)", sentence, re.IGNORECASE)
        if match:
            actor = participant(match[1])
            target = actor if match[2].casefold() in ("себя", "herself", "himself", "themself") else participant(match[2])
            return apply("past", apply("see", actor, target))
        raise Unsupported("Предложение вне контролируемой грамматики")

    root = visit(text)
    return canonical({"entities": declarations, "root": root})


def render(scene, language):
    validate(scene)
    if language not in ("ru", "en"):
        raise Unsupported("Неизвестный язык выражения")
    ru = language == "ru"
    declarations = scene["entities"]
    named = [v["value"] for v in declarations.values() if v["concept"] == cid("human") and v["value"] is not None]
    if len(set(named)) != len(named):
        raise Unsupported("Одноимённые участники требуют внешнего уточнения")

    def participant(term, case=0):
        if "unknown" in term:
            return "неизвестному" if ru else "someone unknown"
        declaration = declarations[term["ref"]]
        value = declaration["value"]
        if value is None:
            return ("Человек", "человеку", "человека")[case] if ru else "a person"
        if value not in NAMES:
            raise Unsupported("Имя вне словаря выражения")
        return NAMES[value][case if ru else 3]

    def visit(term):
        key, args = term["concept"], term["args"]
        if key == cid("possible"):
            return ("Возможно, что " if ru else "Possibly, ") + visit(args[0])
        if key == cid("not"):
            return ("Неверно, что " if ru else "It is false that ") + visit(args[0])
        if key == cid("think"):
            return participant(args[0]) + (" думает, что " if ru else " thinks that ") + visit(args[1])
        if key == cid("if"):
            return ("Если " if ru else "If ") + visit(args[0]) + ("; то " if ru else "; then ") + visit(args[1])
        if key == cid("past"):
            inner = args[0]
            negative = inner["concept"] == cid("not")
            if negative:
                inner = inner["args"][0]
            predicate, roles = inner["concept"], inner["args"]
            actor = participant(roles[0])
            if predicate == cid("give"):
                item_concept = declarations[roles[1]["ref"]]["concept"]
                if item_concept not in (cid("book"), cid("key")):
                    raise Unsupported("Предмет вне словаря")
                thing = ("книгу" if item_concept == cid("book") else "ключ") if ru else ("a book" if item_concept == cid("book") else "a key")
                feminine = declarations[roles[0]["ref"]]["value"] in ("Мария", "Анна", "Елена")
                verb = ("дала" if feminine else "дал") if ru else "gave"
                if negative:
                    verb = "не " + verb if ru else "did not give"
                return f"{actor} {verb} {thing} " + ("" if ru else "to ") + participant(roles[2], 1)
            if predicate == cid("see") and not negative:
                target = "себя" if ru else "themself"
                if roles[0] != roles[1]:
                    target = participant(roles[1], 2)
                feminine = declarations[roles[0]["ref"]]["value"] in ("Мария", "Анна", "Елена")
                verb = ("увидела" if feminine else "увидел") if ru else "saw"
                return f"{actor} {verb} {target}"
        raise Unsupported("Конструкция вне грамматики выражения")

    return visit(scene["root"]) + "."
