"""Авторские gold-конструкции, заданные независимо от языкового парсера."""

from .representation import apply, entity, ref, unknown


def transfer(actor="Мария", recipient="Игорь", item="book"):
    return {"entities": {"a": entity("human", actor), "k": entity(item), "b": entity("human", recipient)},
            "root": apply("past", apply("give", ref("a"), ref("k"), ref("b")))}


def cases():
    positive = transfer()
    reversed_roles = transfer("Игорь", "Мария")
    negative = transfer("Олег", "Елена", "key")
    negative["root"]["args"][0] = apply("not", negative["root"]["args"][0])
    possible = transfer("Анна", "Борис", "key")
    possible["root"] = apply("possible", possible["root"])
    belief = transfer("Игорь", "Анна", "key")
    belief["entities"]["holder"] = entity("human", "Мария")
    belief["root"] = apply("think", ref("holder"), belief["root"])
    two_people = {"entities": {"a": entity("human"), "b": entity("human")},
                  "root": apply("past", apply("see", ref("a"), ref("b")))}
    reflexive = {"entities": {"a": entity("human")}, "root": apply("past", apply("see", ref("a"), ref("a")))}
    missing = transfer()
    missing["entities"].pop("b")
    missing["root"]["args"][0]["args"][2] = unknown()
    condition = transfer()
    condition["entities"].update({"x": entity("human", "Анна"), "y": entity("human", "Олег"), "z": entity("key")})
    condition["root"] = apply("if", condition["root"], apply("past", apply("give", ref("x"), ref("z"), ref("y"))))
    negated_belief = {"entities": belief["entities"], "root": apply("not", belief["root"])}
    return [
        ("roles", "positive", "Мария дала книгу Игорю.", "Maria gave a book to Igor.", positive),
        ("roles", "reversed", "Игорь дал книгу Марии.", "Igor gave a book to Maria.", reversed_roles),
        ("paraphrase", "received", "Игорь получил книгу от Марии.", "Igor received a book from Maria.", positive),
        ("modifiers", "negative", "Олег не дал ключ Елене.", "Oleg did not give a key to Elena.", negative),
        ("modifiers", "possible", "Возможно, что Анна дала ключ Борису.", "Possibly, Anna gave a key to Boris.", possible),
        ("nesting", "belief", "Мария думает, что Игорь дал ключ Анне.", "Maria thinks that Igor gave a key to Anna.", belief),
        ("nesting", "negated_belief", "Неверно, что Мария думает, что Игорь дал ключ Анне.", "It is false that Maria thinks that Igor gave a key to Anna.", negated_belief),
        ("same_concept", "two_people", "Человек увидел человека.", "A person saw a person.", two_people),
        ("references", "reflexive", "Человек увидел себя.", "A person saw themself.", reflexive),
        ("uncertainty", "missing", "Мария дала книгу неизвестному.", "Maria gave a book to someone unknown.", missing),
        ("conditional", "condition", "Если Мария дала книгу Игорю; то Анна дала ключ Олегу.", "If Maria gave a book to Igor; then Anna gave a key to Oleg.", condition),
    ]
