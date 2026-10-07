"""Проверки наблюдений, группировки и атомарного семейного ревью."""

from copy import deepcopy
import hashlib

from fastapi.testclient import TestClient
import pytest

from neuroliq.lexical_workspace import (WorkspaceStore, build_workspace, evidence_order,
                                       family_view, mappings, review)
from neuroliq.m6_2 import tokenize
from neuroliq.web import create_app


def corpus():
    return [("а.txt", "Школа открыта. Школы работают. В школе уроки. " * 6),
            ("б.txt", "Другая школа закрыта. Школы спорят. В школе ремонт. " * 3)]


def test_grouping_deterministic_conservative_and_not_transitive():
    documents = [("тест", "школа школы школе школа школы школе "
                  "школьник школьников школьник школьников "
                  "abc abc 1234 1234 и и редкость")]
    a, b = build_workspace(documents), build_workspace(documents)
    assert a["families"] == b["families"]
    assert a["occurrences"] == b["occurrences"]
    groups = [f["forms"] for f in a["families"]]
    assert ["школа", "школе", "школы"] in groups
    assert ["школьник", "школьников"] in groups
    assert not any("abc" in g or "и" in g or "редкость" in g for g in groups)
    members = [i for f in a["families"] for i in f["members"]]
    assert len(members) == len(set(members))
    assert a["diagnostics"]["grouped_occurrences"] + a["diagnostics"]["ungrouped_occurrences"] == len(a["occurrences"])


def test_exact_batch_and_unicode_offsets_preserve_source():
    text = "И\u0306ван Straße Ёлка, ёлки!"
    w = build_workspace([("оригинал", text), ("другой", "школа школа")], limit=6)
    assert len(w["occurrences"]) == 6
    assert len(w["sources"]) == 1
    assert [o["key"] for o in w["occurrences"]] == list(tokenize(text))[:6]
    for o in w["occurrences"]:
        s = w["sources"][o["source_id"]]["text"]
        assert s[o["start"]:o["end"]].casefold() == o["key"]
    assert w["sources"][0]["text"].endswith("!")
    assert w["sources"][0]["original_text"] == text
    assert w["sources"][0]["sha256"] == hashlib.sha256(text.encode('utf-8')).hexdigest()
    assert w['parameters']['min_frequency'] == 2


def test_no_read_of_next_document_after_limit():
    def documents():
        yield "один", "школа школа"
        raise AssertionError("Следующий документ не должен запрашиваться")
    assert len(build_workspace(documents(), 2)["occurrences"]) == 2


def test_evidence_all_members_once_and_context_auditable():
    w = build_workspace(corpus())
    f = next(f for f in w["families"] if "школа" in f["forms"])
    order, reasons = evidence_order(w, f)
    assert set(order) == set(f["members"])
    assert len(order) == len(set(order))
    assert {w["occurrences"][i]["key"] for i in order[:3]} == set(f["forms"])
    assert any(reason == "Другой источник" for reason in reasons.values())
    assert any("Редкое" in reason for reason in reasons.values())
    for example in family_view(w, f)["examples"]:
        source = w["sources"][example["source_id"]]
        assert example["reference"] == source["reference"]
        assert example["surface"].casefold() == example["key"]


def test_bulk_mapping_split_forms_and_occurrences_provenance():
    w = build_workspace(corpus())
    f = next(f for f in w["families"] if "школа" in f["forms"])
    original = set(f["members"])
    observations = deepcopy(w["occurrences"])
    sources = deepcopy(w["sources"])
    selected = next(i for i in f["members"] if w["occurrences"][i]["key"] == "школа")
    review(w, f["id"], "split", "Исследователь", "Другие контексты", [selected], ["школы"])
    child = w["families"][w["families"].index(f) + 1]
    assert selected in child["members"]
    assert "школы" not in f["forms"]
    assert set(child["members"]) | set(f["members"]) == original
    assert not set(child["members"]) & set(f["members"])
    assert w["events"][0]["members_before"] == sorted(original)
    assert child["parent"] == f["id"]
    review(w, f["id"], "accept", "Исследователь", "Проверены контексты")
    review(w, child["id"], "reject", "Исследователь", "Недостаточно оснований")
    assert mappings(w) == [{"family_id": f["id"], "mapping_id": f["mapping_id"], "occurrence_ids": f["members"]}]
    assert w["occurrences"] == observations and w["sources"] == sources
    assert set(mappings(w)[0]) == {"family_id", "mapping_id", "occurrence_ids"}
    with pytest.raises(ValueError):
        review(w, f["id"], "split", "Исследователь", "Поздно", [f["members"][0]])


@pytest.mark.parametrize("selection", [[], [-1], [9999], "all"])
def test_invalid_split_atomic_in_storage(tmp_path, selection):
    store = WorkspaceStore(tmp_path / "workspace.db")
    w = build_workspace(corpus())
    store.create(w)
    f = w["families"][0]
    selection = f["members"] if selection == "all" else selection
    with pytest.raises(ValueError):
        store.decide(w["id"], 0, family_id=f["id"], action="split", reviewer="Автор", note="Причина", selected=selection)
    assert store.load(w["id"]) == w


def test_restart_persistence_more_and_stale_revision(tmp_path):
    path = tmp_path / "workspace.db"
    store = WorkspaceStore(path)
    w = build_workspace(corpus())
    store.create(w)
    f = w["families"][0]
    updated = store.decide(w["id"], 0, family_id=f["id"], action="more", reviewer="Автор", note="")
    assert updated["families"][0]["shown"] == 16
    store = WorkspaceStore(path)
    assert store.load(w["id"]) == updated
    with pytest.raises(RuntimeError):
        store.decide(w["id"], 0, family_id=f["id"], action="reject", reviewer="Автор", note="Причина")
    assert store.load(w["id"]) == updated
    store.decide(w["id"], 1, family_id=f["id"], action="accept", reviewer="Автор", note="Контексты проверены")
    assert mappings(WorkspaceStore(path).load(w["id"]))


@pytest.mark.parametrize('change', [
    {'note':'   '}, {'reviewer':'   '}, {'forms':['чужая'], 'action':'split'},
])
def test_rejected_decision_preserves_everything(tmp_path, change):
    store = WorkspaceStore(tmp_path / 'atomic.db')
    w = build_workspace(corpus())
    store.create(w)
    payload = {'family_id':w['families'][0]['id'], 'action':'accept', 'reviewer':'Автор', 'note':'Причина'}
    payload.update(change)
    with pytest.raises(ValueError):
        store.decide(w['id'], 0, **payload)
    assert store.load(w['id']) == w


def test_api_end_to_end_restart_and_boundaries(tmp_path):
    path = tmp_path / "api.db"
    client = TestClient(create_app(workspace_path=path))
    assert client.get('/lexical').status_code == 200
    for asset in ('lexical.js', 'lexical.css'):
        assert client.get('/static/' + asset).status_code == 200
    response = client.post('/api/lexical', json={"title":"Проверка", "documents":[{"reference":r,"text":t} for r,t in corpus()]})
    assert response.status_code == 201
    wid = response.json()['id']
    base = '/api/lexical/' + wid
    summary = client.get(base).json()
    fid = summary['families'][0]['id']
    url = base + '/families/' + fid
    assert len(client.get(url).json()['examples']) == 8
    payload = {"revision":0,"action":"more","reviewer":"Автор"}
    assert client.post(url, json=payload).status_code == 200
    assert client.post(url, json=payload).status_code == 409
    payload.update(revision=1,action='split',note='Отдельная форма',forms=['школы'])
    assert client.post(url,json=payload).status_code == 200
    families = client.get(base).json()['families']
    child = next(f for f in families if f['parent'] == fid)
    payload.update(revision=2,action='accept',forms=[])
    assert client.post(url,json=payload).status_code == 200
    payload.update(revision=3,action='reject')
    assert client.post(base + '/families/' + child['id'],json=payload).status_code == 200
    client = TestClient(create_app(workspace_path=path))
    family = client.get(url).json()
    assert family['status'] == 'accepted' and len(family['examples']) == 16
    assert client.get(base + '/sources/0').json()['text'] == corpus()[0][1]
    exported = client.get(base + '/export').json()
    assert exported['mappings']
    assert len(exported['workspace']['events']) == 4
    assert len(client.get('/api/lexical').json()) == 1
    for suffix in ('/sources/-1','/sources/999','/families/no-such-family'):
        assert client.get(base + suffix).status_code == 404
    assert client.get('/api/lexical/absent').status_code == 404
    assert client.post(url,json={**payload,'revision':4,'action':'accept'}).status_code == 422
    assert client.post(url,json={**payload,'revision':4,'action':'PLURAL'}).status_code == 422
    assert client.post(url,json={**payload,'revision':4,'semantic_label':'NOUN'}).status_code == 422


@pytest.mark.parametrize('body', [
    {'title':'Тест'}, {'title':'Тест','limit':True}, {'title':'Тест','limit':0},
    {'title':'Тест','limit':100001}, {'title':'Тест','extra':1},
    {'title':'Тест','source':'dataset','documents':[{'reference':'x','text':'x'}]},
])
def test_api_rejects_invalid_batches_without_persistence(tmp_path, body):
    client = TestClient(create_app(workspace_path=tmp_path / 'api.db'))
    assert client.post('/api/lexical',json=body).status_code == 422
    assert client.get('/api/lexical').json() == []


def test_dataset_api_uses_existing_adapter_and_source_revision(tmp_path, monkeypatch):
    monkeypatch.setattr('neuroliq.lexical_api.validation_documents', lambda: iter(['школа школы школа школы']))
    client = TestClient(create_app(workspace_path=tmp_path / 'api.db'))
    response = client.post('/api/lexical',json={'title':'Корпус','source':'dataset','limit':3})
    assert response.status_code == 201
    base = '/api/lexical/' + response.json()['id']
    source = client.get(base + '/sources/0').json()
    assert '1082c2c8ac044d5fe1a9a27cb942e98ba7fa3110' in source['reference']
    assert source['reference'].endswith('#row=0')
    assert source['processed_tokens'] == 3
