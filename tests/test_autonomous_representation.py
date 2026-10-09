from copy import deepcopy
import pytest
from neuroliq.autonomous.representation import Invalid, apply, canonical, entity, ref, signature, unknown, validate


def transfer():
    return {"entities": {"a": entity("human", "Мария"), "b": entity("human", "Игорь"), "k": entity("book")},
            "root": apply("past", apply("give", ref("a"), ref("k"), ref("b")))}


def test_alpha_renaming_and_identity():
    scene = transfer()
    other = deepcopy(scene)
    other["entities"] = {"new": other["entities"]["a"], "k": other["entities"]["k"], "b": other["entities"]["b"]}
    other["root"]["args"][0]["args"][0] = ref("new")
    assert signature(scene) == signature(other)
    assert canonical(canonical(scene)) == canonical(scene)
    reflexive = {"entities": {"a": entity("human", "Мария")}, "root": apply("see", ref("a"), ref("a"))}
    two = {"entities": {"a": entity("human", "Мария"), "b": entity("human", "Мария")}, "root": apply("see", ref("a"), ref("b"))}
    assert signature(reflexive) != signature(two)


def test_roles_modifiers_and_scopes():
    scene = transfer()
    reversed_scene = deepcopy(scene)
    reversed_scene["root"]["args"][0]["args"] = [ref("b"), ref("k"), ref("a")]
    assert signature(scene) != signature(reversed_scene)
    give = scene["root"]["args"][0]
    variants = [apply("past", give), apply("not", give), apply("possible", give), apply("think", ref("a"), give)]
    assert len({signature({"entities": scene["entities"], "root": root}) for root in variants}) == 4
    see = apply("see", ref("a"), ref("b"))
    left = {"entities": scene["entities"], "root": apply("not", apply("all", give, see))}
    right = {"entities": scene["entities"], "root": apply("all", apply("not", give), see)}
    assert signature(left) != signature(right)


@pytest.mark.parametrize("mutation", [
    lambda s: s["root"]["args"][0]["args"].append(ref("a")),
    lambda s: s["root"]["args"][0]["args"].__setitem__(1, ref("a")),
    lambda s: s["root"]["args"].__setitem__(0, ref("missing")),
    lambda s: s["entities"].__setitem__("unused", entity("human")),
    lambda s: s["entities"]["a"].__setitem__("value", float("nan")),
])
def test_invalid(mutation):
    scene = transfer()
    mutation(scene)
    with pytest.raises(Invalid):
        validate(scene)


def test_unknown_and_depth_budget():
    scene = {"entities": {"a": entity("human"), "k": entity("book")},
             "root": apply("give", ref("a"), ref("k"), unknown())}
    validate(scene)
    for _ in range(16):
        scene["root"] = apply("not", scene["root"])
    with pytest.raises(Invalid, match="бюджет"):
        validate(scene)
