"""Постоянные ID, структурная проекция и точное продолжение корпуса."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from neuroliq.lexical_workspace import WorkspaceStore, build_workspace
from neuroliq.web import create_app


def entries(store):
    return {e['surface']: e['concept_id'] for e in store.dictionary()['entries']}


def pairs(store):
    with store.connect() as db:
        return set(db.execute('SELECT concept_a, concept_b FROM l0_connections'))


def test_persistent_dictionary_connections_and_source_boundaries(tmp_path):
    path = tmp_path / 'workspace.db'
    store = WorkspaceStore(path)
    first = build_workspace([('а', 'ШКОЛА школы школа школа'), ('б', 'урок')])
    store.create(first)
    ids = entries(store)
    assert len(ids) == 3
    assert pairs(store) == {tuple(sorted((ids['школа'], ids['школы'])))}
    store = WorkspaceStore(path)
    store.create(build_workspace([('в', 'школа школы школа урок новый')]))
    newer = entries(store)
    assert all(newer[k] == v for k, v in ids.items())
    assert newer['новый'] not in ids.values()
    assert len(pairs(store)) == 3
    assert store.load(first['id'])['occurrences'] == first['occurrences']
    with store.connect() as db:
        assert [r[1] for r in db.execute('PRAGMA table_info(l0_concepts)')] == ['id']
        assert [r[1] for r in db.execute('PRAGMA table_info(l0_connections)')] == ['concept_a', 'concept_b']


def test_dataset_continuation_inside_document_restart_and_no_document_bridge(tmp_path):
    path = tmp_path / 'workspace.db'
    docs = [('row=0', 'И\u0306ван Straße Ёлка, ёлки!'), ('row=1', ''), ('row=2', 'новый урок')]
    store = WorkspaceStore(path)
    a = store.create_dataset(iter(docs), 'fixed', 3, 'первый')
    assert a['corpus']['end']['ordinal'] == 3
    store = WorkspaceStore(path)
    b = store.create_dataset(iter(docs), 'fixed', 3, 'второй')
    assert [o['ordinal'] for o in b['occurrences']] == [3, 4, 5]
    assert [o['key'] for o in b['occurrences']] == [',', 'ёлки', '!']
    for o in b['occurrences']:
        text = b['sources'][o['source_id']]['text']
        assert text[o['start']:o['end']].casefold() == o['key']
    ids = entries(store)
    assert tuple(sorted((ids['ёлка'], ids[',']))) in pairs(store)
    c = store.create_dataset(iter(docs), 'fixed', 10, 'третий')
    assert [o['key'] for o in c['occurrences']] == ['новый', 'урок']
    assert tuple(sorted((ids['!'], entries(store)['новый']))) not in pairs(store)
    before = store.l0_stats()
    with pytest.raises(ValueError, match='исчерпан'):
        store.create_dataset(iter(docs), 'fixed', 10, 'пустой')
    assert store.l0_stats() == before
    assert len(store.list()) == 3
    assert len(pairs(store)) == 6


def test_failed_batch_rolls_back_projection_cursor_and_snapshot(tmp_path):
    store = WorkspaceStore(tmp_path / 'workspace.db')
    docs = [('row=0', 'один два три четыре')]
    store.create_dataset(iter(docs), 'fixed', 2, 'первый')
    before, ids = store.l0_stats(), entries(store)
    insert = store._insert
    def fail(db, workspace):
        insert(db, workspace)
        raise RuntimeError('имитация отказа')
    store._insert = fail
    with pytest.raises(RuntimeError):
        store.create_dataset(iter(docs), 'fixed', 2, 'второй')
    assert store.l0_stats() == before
    assert entries(store) == ids
    assert len(store.list()) == 1
    store._insert = insert
    assert [o['key'] for o in store.create_dataset(iter(docs), 'fixed', 2, 'повтор')['occurrences']] == ['три', 'четыре']


def test_concurrent_dataset_batches_are_serialized(tmp_path):
    path = tmp_path / 'workspace.db'
    WorkspaceStore(path)
    def batch(_):
        return WorkspaceStore(path).create_dataset([('0', 'один два три четыре')], 'fixed', 2, 'батч')
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(batch, range(2)))
    assert sorted([o['ordinal'] for o in b['occurrences']] for b in batches) == [[0, 1], [2, 3]]
    assert WorkspaceStore(path).l0_stats()['connections'] == 3


def test_api_lexical_concept_neighborhood_and_review_independence(tmp_path, monkeypatch):
    import neuroliq.lexical_api as api
    path = tmp_path / 'workspace.db'
    monkeypatch.setattr(api, 'validation_documents', lambda: iter(['школа школы школа школы урок']))
    client = TestClient(create_app(workspace_path=path))
    a = client.post('/api/lexical', json={'title':'первый', 'source':'dataset', 'limit':2}).json()['id']
    client = TestClient(create_app(workspace_path=path))
    b = client.post('/api/lexical', json={'title':'второй', 'source':'dataset', 'limit':3}).json()['id']
    exported = client.get(f'/api/lexical/{b}/export').json()['workspace']
    assert [o['ordinal'] for o in exported['occurrences']] == [2, 3, 4]
    found = client.get('/api/l0/dictionary', params={'q':'ШКОЛ'}).json()['entries']
    assert len(found) == 2
    local = client.post('/api/lexical', json={'title':'ревью', 'documents':[{'reference':'текст', 'text':'школа школы школа школы'}]}).json()['id']
    summary = client.get(f'/api/lexical/{local}').json()
    f = summary['families'][0]
    family = client.get(f'/api/lexical/{local}/families/{f["id"]}').json()
    concept = family['concept_ids']['школа']
    before = client.get('/api/l0').json()
    client.post(f'/api/lexical/{local}/families/{f["id"]}', json={'revision':0,'action':'split','reviewer':'тест','forms':['школы']}).raise_for_status()
    client.post(f'/api/lexical/{local}/families/{f["id"]}', json={'revision':1,'action':'accept','reviewer':'тест'}).raise_for_status()
    child = client.get(f'/api/lexical/{local}').json()['families'][1]
    client.post(f'/api/lexical/{local}/families/{child["id"]}', json={'revision':2,'action':'reject','reviewer':'тест'}).raise_for_status()
    assert client.get('/api/l0').json() == before
    family = client.get(f'/api/lexical/{local}/families/{f["id"]}').json()
    assert family['mapping_id'] != concept
    graph = client.get(f'/api/l0/concepts/{concept}').json()
    assert graph['degree'] == 1
    assert len(graph['connections']) == 1
    assert {n['id'] for n in graph['concepts']} == {e['concept_id'] for e in found}
    assert client.get('/api/l0/concepts/unknown').status_code == 404
    assert client.get('/api/l0/dictionary?limit=201').status_code == 422
    assert client.get('/l0').status_code == 200
    assert 'concept_ids' in client.get('/static/lexical.js').text
    assert '/l0' in client.get('/lexical').text
    assert 'cytoscape' in client.get('/static/l0.js').text
    assert client.get(f'/api/lexical/{a}').status_code == 200


def test_bounded_induced_subgraph_and_literal_search(tmp_path):
    store = WorkspaceStore(tmp_path / 'workspace.db')
    store.create(build_workspace([('а', 'центр один центр два центр три один два')]))
    ids = entries(store)
    full = store.l0_neighborhood(ids['центр'])
    assert full['degree'] == 3 and len(full['connections']) == 5
    partial = store.l0_neighborhood(ids['центр'], 1)
    assert partial['degree'] == 3 and partial['truncated']
    assert len(partial['concepts']) == 2 and len(partial['connections']) == 1
    assert store.dictionary('%')['entries'] == []
    assert store.dictionary('_')['entries'] == []
    assert store.dictionary('', 1)['truncated']
