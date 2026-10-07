"""Общий граф и ordered routes: CRUD, restart, обмен и изоляция."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from neuroliq.lexical_workspace import WorkspaceStore, build_workspace
from neuroliq.thought_workbench import Concept, Snapshot, ThoughtStore
from neuroliq.web import create_app

BASE = '/api/thought-workbench'


def uid(n):
    return str(UUID(int=n))


def document():
    return {
        'format': 'neuroliq.thought-workbench', 'format_version': 2,
        'concepts': [{'id': uid(1), 'annotation': 'HUMAN'}, {'id': uid(2), 'annotation': 'SEE'}],
        'connections': [{'concept_a': uid(1), 'concept_b': uid(2)}],
        'sources': [{'id': uid(3), 'text': '  И\u0306горь видит человека.\r\n\t', 'context': 'Без нормализации\n{заметки}\u0000'}],
        'thoughts': [
            {'id': uid(4), 'source_id': uid(3), 'annotation': 'Возврат к HUMAN', 'route': [uid(1), uid(2), uid(1)]},
            {'id': uid(5), 'source_id': uid(3), 'annotation': 'Другой маршрут', 'route': [uid(2), uid(1)]},
        ],
    }


def test_crud_restart_shared_graph_and_exact_exchange(tmp_path):
    path = tmp_path / 'shared.db'
    with TestClient(create_app(workspace_path=path)) as client:
        assert client.get('/thought-workbench').status_code == 200
        for asset in ('thought-workbench.js', 'thought-workbench.css', 'vendor/cytoscape.min.js'):
            assert client.get('/static/' + asset).status_code == 200
        for page in ('/', '/lexical', '/l0'):
            assert '/thought-workbench' in client.get(page).text
        doc = document()
        for collection in ('concepts', 'connections', 'sources', 'thoughts'):
            for record in doc[collection]:
                assert client.post(f'{BASE}/{collection}', json=record).status_code == 201
        saved = client.get(BASE).json()
        assert saved == doc
        assert len(saved['concepts']) == 2 and len(saved['connections']) == 1
        for collection in ('concepts', 'sources', 'thoughts'):
            record = deepcopy(saved[collection][0])
            record['context' if collection == 'sources' else 'annotation'] = 'Изменение\r\n'
            assert client.put(f'{BASE}/{collection}/{record["id"]}', json=record).status_code == 200
        canonical = client.get(BASE + '/export').content
        for url in (f'/concepts/{uid(1)}', f'/sources/{uid(3)}', f'/connections/{uid(2)}/{uid(1)}'):
            assert client.delete(BASE + url).status_code == 422
            assert client.get(BASE + '/export').content == canonical
    with TestClient(create_app(workspace_path=path)) as restarted:
        assert restarted.get(BASE + '/export').content == canonical
        assert next(t for t in restarted.get(BASE).json()['thoughts'] if t['id'] == uid(4))['route'] == [uid(1), uid(2), uid(1)]
        assert restarted.put(BASE, content=canonical).status_code == 200
        assert restarted.get(BASE + '/export').content == canonical
        reordered = json.loads(canonical)
        for collection in ('concepts', 'connections', 'sources', 'thoughts'):
            reordered[collection].reverse()
        c = reordered['connections'][0]
        c['concept_a'], c['concept_b'] = c['concept_b'], c['concept_a']
        assert restarted.put(BASE, json=reordered).status_code == 200
        assert restarted.get(BASE + '/export').content == canonical
        for n in (4, 5):
            assert restarted.delete(f'{BASE}/thoughts/{uid(n)}').status_code == 200
        assert restarted.delete(f'{BASE}/concepts/{uid(1)}').status_code == 422
        assert restarted.delete(f'{BASE}/connections/{uid(2)}/{uid(1)}').status_code == 200
        assert restarted.delete(f'{BASE}/connections/{uid(1)}/{uid(2)}').status_code == 404
        for collection, ids in (('sources', [3]), ('concepts', [1, 2])):
            for n in ids:
                assert restarted.delete(f'{BASE}/{collection}/{uid(n)}').status_code == 200
                assert restarted.delete(f'{BASE}/{collection}/{uid(n)}').status_code == 404
        assert restarted.get(BASE).json() == Snapshot().model_dump(mode='json')
    with TestClient(create_app(workspace_path=tmp_path / 'other.db')) as fresh:
        assert fresh.put(BASE, content=canonical).status_code == 200
        assert fresh.get(BASE + '/export').content == canonical


@pytest.mark.parametrize('case', ['version', 'bool_version', 'missing_header', 'duplicate', 'uuid', 'source',
                                 'route_concept', 'endpoint', 'connection_duplicate', 'edge_type', 'strength',
                                 'elements', 'literal', 'route_type', 'route_item', 'missing_connection', 'extra', 'surrogate'])
def test_invalid_import_is_atomic(tmp_path, case):
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=document()).status_code == 200
        before = client.get(BASE + '/export').content
        bad = deepcopy(document())
        t = bad['thoughts'][0]
        if case == 'version': bad['format_version'] = 1
        elif case == 'bool_version': bad['format_version'] = True
        elif case == 'missing_header': del bad['connections']
        elif case == 'duplicate': bad['concepts'].append(bad['concepts'][0])
        elif case == 'uuid': bad['concepts'][0]['id'] = 'HUMAN'
        elif case == 'source': t['source_id'] = uid(99)
        elif case == 'route_concept': t['route'][0] = uid(99)
        elif case == 'endpoint': bad['connections'][0]['concept_b'] = uid(99)
        elif case == 'connection_duplicate': bad['connections'].append({'concept_a': uid(2), 'concept_b': uid(1)})
        elif case == 'edge_type': bad['connections'][0]['type'] = 'SUBJECT_OF'
        elif case == 'strength': bad['connections'][0]['strength'] = 1
        elif case == 'elements': t['elements'] = []
        elif case == 'literal': t['route'][0] = {'value': 'Игорь'}
        elif case == 'route_type': t['route'] = 'HUMAN'
        elif case == 'route_item': t['route'][0] = 1
        elif case == 'missing_connection': bad['connections'] = []
        elif case == 'extra': bad['runtime'] = {}
        elif case == 'surrogate': bad['sources'][0]['text'] = '\ud800'
        assert client.put(BASE, content=json.dumps(bad)).status_code == 422
        assert client.get(BASE + '/export').content == before


@pytest.mark.parametrize('raw', ['{', '{}', '[]', '{"format_version":2,"format_version":1}',
                               '{"x":NaN}', '{"x":Infinity}', b'\xff'])
def test_bad_json_is_atomic(tmp_path, raw):
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=document()).status_code == 200
        before = client.get(BASE + '/export').content
        assert client.put(BASE, content=raw).status_code == 422
        assert client.get(BASE + '/export').content == before


def test_route_order_not_sorted_and_repetition_not_deduplicated(tmp_path):
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=document()).status_code == 200
        before = client.get(BASE + '/export').content
        t = document()['thoughts'][0]
        t['route'] = [uid(2), uid(1), uid(2), uid(1)]
        assert client.put(f'{BASE}/thoughts/{t["id"]}', json=t).status_code == 200
        assert client.get(BASE).json()['thoughts'][-1]['route'] == t['route']
        assert client.get(BASE + '/export').content != before
        t['route'] = [uid(1)]
        assert client.put(f'{BASE}/thoughts/{t["id"]}', json=t).status_code == 200
        t['route'] = []
        assert client.put(f'{BASE}/thoughts/{t["id"]}', json=t).status_code == 200
        assert len(client.get(BASE).json()['concepts']) == 2


def test_crud_rejection_and_annotations_preserve_topology(tmp_path):
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=document()).status_code == 200
        before = client.get(BASE + '/export').content
        t = document()['thoughts'][0]
        bad = {**t, 'id': uid(99)}
        assert client.put(f'{BASE}/thoughts/{t["id"]}', json=bad).status_code == 422
        assert client.put(f'{BASE}/thoughts/{bad["id"]}', json=bad).status_code == 404
        assert client.post(BASE + '/sources', content='{').status_code == 422
        assert client.post(BASE + '/connections', json={'concept_a':uid(2), 'concept_b':uid(1)}).status_code == 422
        assert client.post(BASE + '/connections', json={'concept_a':uid(1), 'concept_b':uid(99)}).status_code == 422
        assert client.get(BASE + '/export').content == before
        concept = {**document()['concepts'][0], 'annotation': 'Произвольная подсказка'}
        assert client.put(f'{BASE}/concepts/{concept["id"]}', json=concept).status_code == 200
        state = client.get(BASE).json()
        assert state['thoughts'] == document()['thoughts']
        assert state['connections'] == document()['connections']


def test_route_only_reference_blocks_deletion(tmp_path):
    doc = document()
    doc['connections'] = []
    doc['thoughts'] = [{**doc['thoughts'][0], 'route': [uid(1)]}]
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=doc).status_code == 200
        assert client.delete(f'{BASE}/concepts/{uid(1)}').status_code == 422
        assert client.delete(f'{BASE}/concepts/{uid(2)}').status_code == 200


def test_isolation_and_transaction_rollback(tmp_path, monkeypatch):
    path = tmp_path / 'shared.db'
    lexical = WorkspaceStore(path)
    batch = build_workspace([('файл', 'школа школы урок')])
    lexical.create(batch)
    tables = ['workspaces', 'l0_concepts', 'l0_connections', 'lexical_dictionary', 'corpus_cursors']
    def other_state():
        with lexical.connect() as db:
            return {table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables}
    before = other_state()
    with TestClient(create_app(workspace_path=path)) as client:
        graph = client.get('/api/experiment').content
        activation = client.get('/api/activation').content
        assert client.put(BASE, json=document()).status_code == 200
        assert client.put(BASE, content=client.get(BASE + '/export').content).status_code == 200
        assert client.get('/api/experiment').content == graph
        assert client.get('/api/activation').content == activation
        assert client.get('/api/lexical/' + batch['id'] + '/export').json()['workspace'] == batch
    assert other_state() == before
    store = ThoughtStore(path)
    saved = store.read().canonical()
    original = store._write
    def fail(db, snapshot):
        original(db, snapshot)
        raise RuntimeError('Имитация сбоя перед commit')
    monkeypatch.setattr(store, '_write', fail)
    with pytest.raises(RuntimeError):
        store.replace(Snapshot())
    assert store.read().canonical() == saved
    lexical.create(build_workspace([('ещё', 'новый текст')]))
    assert store.read().canonical() == saved


def test_parallel_catalog_writes(tmp_path):
    store = ThoughtStore(tmp_path / 'db')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: store.mutate('concepts', uid(n), Concept(id=uid(n), annotation=str(n)), True), range(1, 101)))
    assert len(store.read().concepts) == 100


def test_destructive_schema_replacement_is_scoped_and_one_time(tmp_path):
    path = tmp_path / 'shared.db'
    lexical = WorkspaceStore(path)
    batch = build_workspace([('файл', 'школа школы')])
    lexical.create(batch)
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE tw_concepts(id TEXT PRIMARY KEY, annotation TEXT);
            CREATE TABLE tw_sources(id TEXT PRIMARY KEY, text TEXT, context TEXT);
            CREATE TABLE tw_thoughts(id TEXT PRIMARY KEY, source_id TEXT REFERENCES tw_sources(id), annotation TEXT);
            CREATE TABLE tw_elements(thought_id TEXT REFERENCES tw_thoughts(id), id TEXT, PRIMARY KEY(thought_id,id));
            CREATE TABLE tw_links(thought_id TEXT, source TEXT, target TEXT, FOREIGN KEY(thought_id,source) REFERENCES tw_elements(thought_id,id));
        ''')
        db.execute('INSERT INTO tw_concepts VALUES (?,?)', (uid(1), 'Старый'))
        db.execute('INSERT INTO tw_sources VALUES (?,?,?)', (uid(3), 'Старый', ''))
        db.execute('INSERT INTO tw_thoughts VALUES (?,?,?)', (uid(4), uid(3), 'Старый'))
        db.execute('INSERT INTO tw_elements VALUES (?,?)', (uid(4), uid(11)))
        db.execute('INSERT INTO tw_links VALUES (?,?,?)', (uid(4), uid(11), uid(11)))
    store = ThoughtStore(path)
    assert store.read() == Snapshot()
    with store.connect() as db:
        assert {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'tw_%'")} == {'tw_concepts', 'tw_connections', 'tw_sources', 'tw_thoughts'}
    store.replace(Snapshot.model_validate(document()))
    assert ThoughtStore(path).read().canonical() == store.read().canonical()
    assert lexical.load(batch['id']) == batch
