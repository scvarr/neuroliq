"""CRUD, точный обмен, restart и границы ручного Workbench."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from neuroliq.lexical_workspace import WorkspaceStore, build_workspace
from neuroliq.thought_workbench import Concept, Snapshot, ThoughtStore
from neuroliq.web import create_app

BASE = "/api/thought-workbench"


def uid(n):
    return str(UUID(int=n))


def document():
    return {
        "format": "neuroliq.thought-workbench", "format_version": 1,
        "concepts": [{"id": uid(1), "annotation": "ЧЕЛОВЕК"}, {"id": uid(2), "annotation": "ДАТЬ"}],
        "sources": [{"id": uid(3), "text": "  И\u0306горь дал книгу Марии.\r\nОн устал.\t", "context": "Без нормализации\n{контекст}"}],
        "thoughts": [{"id": uid(4), "source_id": uid(3), "annotation": "Передача",
                      "elements": [
                          {"id": uid(11), "kind": "concept", "concept_id": uid(1), "annotation": "Первый участник"},
                          {"id": uid(12), "kind": "concept", "concept_id": uid(1), "annotation": "Другой участник"},
                          {"id": uid(13), "kind": "concept", "concept_id": uid(2)},
                          {"id": uid(14), "kind": "literal", "value": '  {"число":9007199254740993} «Игорь»\r\n\t\u0000'}],
                      "links": [{"source": uid(13), "target": uid(11)}, {"source": uid(13), "target": uid(12)},
                                {"source": uid(11), "target": uid(14)}, {"source": uid(12), "target": uid(13)}]}]
    }


def test_crud_restart_and_exact_exchange(tmp_path):
    path = tmp_path / "shared.sqlite3"
    with TestClient(create_app(workspace_path=path)) as client:
        assert client.get('/thought-workbench').status_code == 200
        for asset in ('thought-workbench.js', 'thought-workbench.css', 'vendor/cytoscape.min.js'):
            assert client.get('/static/' + asset).status_code == 200
        for page in ('/', '/lexical', '/l0'):
            assert '/thought-workbench' in client.get(page).text
        doc = document()
        for collection in ('concepts', 'sources', 'thoughts'):
            for record in doc[collection]:
                assert client.post(f'{BASE}/{collection}', json=record).status_code == 201
        assert client.post(f'{BASE}/concepts', json=doc['concepts'][0]).status_code == 422
        thought = client.get(BASE).json()['thoughts'][0]
        assert thought['elements'][0]['concept_id'] == thought['elements'][1]['concept_id']
        assert thought['elements'][0]['id'] != thought['elements'][1]['id']
        assert sorted(thought['links'], key=lambda l: (l['source'], l['target'])) == sorted(doc['thoughts'][0]['links'], key=lambda l: (l['source'], l['target']))
        assert thought['elements'][3]['value'] == doc['thoughts'][0]['elements'][3]['value']
        assert client.get(BASE).json()['sources'] == doc['sources']
        for collection in ('concepts', 'sources', 'thoughts'):
            record = client.get(BASE).json()[collection][0]
            record['context' if collection == 'sources' else 'annotation'] = 'Изменение\r\n'
            assert client.put(f'{BASE}/{collection}/{record["id"]}', json=record).status_code == 200
        canonical = client.get(BASE + '/export').content
        assert client.delete(f'{BASE}/concepts/{uid(1)}').status_code == 422
        assert client.delete(f'{BASE}/sources/{uid(3)}').status_code == 422
        assert client.get(BASE + '/export').content == canonical
    with TestClient(create_app(workspace_path=path)) as restarted:
        assert restarted.get(BASE + '/export').content == canonical
        assert restarted.put(BASE, content=canonical).status_code == 200
        assert restarted.get(BASE + '/export').content == canonical
        reordered = json.loads(canonical)
        reordered['concepts'].reverse()
        reordered['thoughts'][0]['elements'].reverse()
        reordered['thoughts'][0]['links'].reverse()
        assert restarted.put(BASE, json=reordered).status_code == 200
        assert restarted.get(BASE + '/export').content == canonical
        t = restarted.get(BASE).json()['thoughts'][0]
        t['elements'] = [e for e in t['elements'] if e['id'] != uid(11)]
        t['links'] = [l for l in t['links'] if uid(11) not in (l['source'], l['target'])]
        assert restarted.put(f'{BASE}/thoughts/{t["id"]}', json=t).status_code == 200
        for collection, ids in (('thoughts', [4]), ('sources', [3]), ('concepts', [1, 2])):
            for n in ids:
                assert restarted.delete(f'{BASE}/{collection}/{uid(n)}').status_code == 200
                assert restarted.delete(f'{BASE}/{collection}/{uid(n)}').status_code == 404
        assert restarted.get(BASE).json() == Snapshot().model_dump(mode='json')
    with TestClient(create_app(workspace_path=tmp_path / 'other.db')) as fresh:
        assert fresh.put(BASE, content=canonical).status_code == 200
        assert fresh.get(BASE + '/export').content == canonical


@pytest.mark.parametrize('case', ['version', 'bool_version', 'missing_header', 'duplicate', 'uuid', 'source',
                                'concept', 'endpoint', 'local_duplicate', 'link_duplicate', 'edge_type',
                                'literal_concept', 'concept_value', 'missing_literal', 'numeric_literal', 'extra'])
def test_invalid_import_is_atomic(tmp_path, case):
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=document()).status_code == 200
        before = client.get(BASE + '/export').content
        bad = deepcopy(document())
        t = bad['thoughts'][0]
        if case == 'version': bad['format_version'] = 2
        elif case == 'bool_version': bad['format_version'] = True
        elif case == 'missing_header': del bad['format']
        elif case == 'duplicate': bad['concepts'].append(bad['concepts'][0])
        elif case == 'uuid': bad['concepts'][0]['id'] = 'ЧЕЛОВЕК'
        elif case == 'source': t['source_id'] = uid(99)
        elif case == 'concept': t['elements'][0]['concept_id'] = uid(99)
        elif case == 'endpoint': t['links'][0]['target'] = uid(99)
        elif case == 'local_duplicate': t['elements'].append(t['elements'][0])
        elif case == 'link_duplicate': t['links'].append(t['links'][0])
        elif case == 'edge_type': t['links'][0]['type'] = 'SUBJECT_OF'
        elif case == 'literal_concept': t['elements'][3]['concept_id'] = uid(1)
        elif case == 'concept_value': t['elements'][0]['value'] = 'Игорь'
        elif case == 'missing_literal': del t['elements'][3]['value']
        elif case == 'numeric_literal': t['elements'][3]['value'] = 1
        elif case == 'extra': bad['runtime'] = {}
        assert client.put(BASE, json=bad).status_code == 422
        assert client.get(BASE + '/export').content == before


@pytest.mark.parametrize('raw', ['{', '{}', '[]', '{"format_version":1,"format_version":2}',
                              '{"x":NaN}', '{"x":Infinity}', b'\xff'])
def test_bad_json_is_atomic(tmp_path, raw):
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=document()).status_code == 200
        before = client.get(BASE + '/export').content
        assert client.put(BASE, content=raw).status_code == 422
        assert client.get(BASE + '/export').content == before


def test_isolation_and_transaction_rollback(tmp_path, monkeypatch):
    path = tmp_path / 'shared.db'
    lexical = WorkspaceStore(path)
    batch = build_workspace([('файл', 'школа школы урок')])
    lexical.create(batch)
    with lexical.connect() as db:
        tables = ['workspaces', 'l0_concepts', 'l0_connections', 'lexical_dictionary', 'corpus_cursors']
        before = {table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables}
    with TestClient(create_app(workspace_path=path)) as client:
        graph = client.get('/api/experiment').content
        activation = client.get('/api/activation').content
        assert client.put(BASE, json=document()).status_code == 200
        assert client.get('/api/experiment').content == graph
        assert client.get('/api/activation').content == activation
        assert client.get('/api/lexical/' + batch['id'] + '/export').json()['workspace'] == batch
    with lexical.connect() as db:
        assert {table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables} == before
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


def test_parallel_catalog_writes_and_local_scope(tmp_path):
    store = ThoughtStore(tmp_path / 'db')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: store.mutate('concepts', uid(n), Concept(id=uid(n), annotation=str(n)), True), range(1, 101)))
    assert len(store.read().concepts) == 100
    doc = document()
    other = deepcopy(doc['thoughts'][0])
    other['id'] = uid(5)
    doc['thoughts'].append(other)
    store.replace(Snapshot.model_validate(doc))
    assert len(store.read().thoughts) == 2


def test_crud_rejection_and_annotations_preserve_structure(tmp_path):
    with TestClient(create_app(workspace_path=tmp_path / 'db')) as client:
        assert client.put(BASE, json=document()).status_code == 200
        before = client.get(BASE + '/export').content
        t = client.get(BASE).json()['thoughts'][0]
        bad = deepcopy(t)
        bad['id'] = uid(99)
        assert client.put(f'{BASE}/thoughts/{t["id"]}', json=bad).status_code == 422
        assert client.put(f'{BASE}/thoughts/{bad["id"]}', json=bad).status_code == 404
        bad = deepcopy(t)
        bad['elements'] = bad['elements'][1:]
        assert client.put(f'{BASE}/thoughts/{t["id"]}', json=bad).status_code == 422
        assert client.post(BASE + '/sources', content='{').status_code == 422
        assert client.get(BASE + '/export').content == before
        concept = client.get(BASE).json()['concepts'][0]
        concept['annotation'] = 'Произвольная новая подсказка'
        assert client.put(f'{BASE}/concepts/{concept["id"]}', json=concept).status_code == 200
        assert client.get(BASE).json()['thoughts'][0] == t
