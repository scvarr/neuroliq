import pytest
from neuroliq.autonomous.language import Unsupported, parse, render
from neuroliq.autonomous.representation import entity, signature


@pytest.mark.parametrize("ru,en", [
    ("Мария дала книгу Игорю.", "Maria gave a book to Igor."),
    ("Игорь получил книгу от Марии.", "Igor received a book from Maria."),
    ("Олег не дал ключ Елене.", "Oleg did not give a key to Elena."),
    ("Возможно, что Анна дала ключ Борису.", "Possibly, Anna gave a key to Boris."),
    ("Мария думает, что Игорь дал ключ Анне.", "Maria thinks that Igor gave a key to Anna."),
    ("Человек увидел человека.", "A person saw a person."),
    ("Человек увидел себя.", "A person saw themself."),
    ("Мария дала книгу неизвестному.", "Maria gave a book to someone unknown."),
    ("Если Мария дала книгу Игорю; то Анна дала ключ Олегу.", "If Maria gave a book to Igor; then Anna gave a key to Oleg."),
    ("Неверно, что Мария думает, что Игорь дал ключ Анне.", "It is false that Maria thinks that Igor gave a key to Anna."),
])
def test_bilingual_composition_and_roundtrip(ru, en):
    left, right = parse(ru, "ru"), parse(en, "en")
    assert signature(left) == signature(right)
    for language in ("ru", "en"):
        assert signature(parse(render(left, language), language)) == signature(left)


@pytest.mark.parametrize("text", ["Она дала книгу Игорю.", "Мария увидела Марию.", "Мария могла бы дать книгу.", "Все люди читают книги."])
def test_explicit_refusals(text):
    with pytest.raises(Unsupported):
        parse(text, "ru")


def test_explicit_context_binding():
    scene = parse("Она дала книгу Игорю.", "ru", {"она": entity("human", "Мария", "previous:r0")})
    assert scene["entities"]["r0"]["origin"] == "previous:r0"
