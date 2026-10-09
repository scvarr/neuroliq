"""P2: явные проекции одного набора минимальных мыслей в три кандидата."""

import json


def atom(concept, ref, value=None):
    return ("atom", concept, ref, value)


def app(concept, *args):
    return ("apply", concept, args)


def route(term):
    if term[0] == "atom":
        return [term[1]]
    prefix = [] if term[1] == "bundle" else [term[1]]
    return prefix + [c for arg in term[2] for c in route(arg)]


def adjacency(term):
    nodes, edges = set(), set()

    def walk(t):
        head = t[1]
        nodes.add(head)
        if t[0] == "apply":
            for arg in t[2]:
                edges.add(tuple(sorted((head, arg[1]))))
                walk(arg)

    walk(term)
    return sorted(nodes), sorted(edges)


def cases():
    a, b = atom("human", "a", "Мария"), atom("human", "b", "Игорь")
    k = atom("book", "k")
    give, see = app("give", a, k, b), app("see", a, b)
    return [
        ("roles", give, app("give", b, k, a)),
        ("references", app("see", a, a), app("see", a, b)),
        ("values", give, app("give", atom("human", "a", "Анна"), k, b)),
        ("same_name", app("see", a, a), app("see", a, atom("human", "b", "Мария"))),
        ("scope", app("not", app("bundle", give, see)), app("bundle", app("not", give), see)),
        ("modifiers", app("past", give), app("possible", give)),
        ("belief", give, app("believe", a, give)),
    ]


def compare():
    results = {name: {} for name in ("adjacency", "route", "composition")}
    for group, left, right in cases():
        results["adjacency"][group] = adjacency(left) != adjacency(right)
        results["route"][group] = route(left) != route(right)
        results["composition"][group] = left != right
    return {"version": 1, "data": "авторские минимальные контрпримеры v1", "results": results}


if __name__ == "__main__":
    print(json.dumps(compare(), ensure_ascii=False, indent=2))
