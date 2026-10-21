import json
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app import config
from backend.app.report_routes import report_router
from eval.quality_contracts import freeze
from test_quality_contracts import dataset, labels, judgment


def test_quality_mode_filters_invalid_files_and_private_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    ids = {}
    for mode in ('sample', 'local'):
        body = dataset()
        body['cases'][0]['source'] = 'synthetic' if mode == 'sample' else 'observed'
        frozen = freeze(body); ratings = labels(frozen)
        ratings['judgments'] = [judgment(reason='PRIVATE REASON', value='4')]
        identifier = str(uuid4()); ids[mode] = identifier
        folder = tmp_path/'runtime/quality'/mode/identifier; folder.mkdir(parents=True)
        (folder/'inputs.json').write_text(json.dumps(frozen))
        (folder/'labels.json').write_text(json.dumps(ratings))
    broken = str(uuid4()); folder = tmp_path/'runtime/quality/sample'/broken; folder.mkdir()
    (folder/'inputs.json').write_text('{incomplete')
    app = FastAPI(); app.include_router(report_router(config.Settings(_env_file=None,data_mode='local',llm_mode='fake')))
    with TestClient(app) as client:
        rows = client.get('/reports/quality?source=sample').json()
        assert {r['id'] for r in rows} == {ids['sample'], broken}
        assert next(r for r in rows if r['id'] == broken)['status'] == 'failed'
        assert [r['id'] for r in client.get('/reports/quality').json()] == [ids['local']]
        response = client.get(f"/reports/quality/{ids['sample']}?source=sample")
        assert response.status_code == 200
        report = response.json()
        assert report['readiness']['cases'] == 1 and report['readiness']['resolved'] == 1
        assert report['metrics'] is None and report['model'] is None
        assert 'PRIVATE REASON' not in response.text and 'reviewers' not in response.text
        assert 'value' not in report['cases'][0]['references'][0]
        filtered = client.get(f"/reports/quality/{ids['sample']}?source=sample&region=absent").json()
        assert filtered['readiness']['cases'] == 0 and filtered['readiness']['reference_items'] == 0
        assert client.get(f"/reports/quality/{ids['local']}?source=sample").status_code == 404
        assert client.get(f'/reports/quality/{broken}?source=sample').status_code == 409
        assert client.get('/reports/quality/not-uuid').status_code == 422
        # A tampered frozen input is never treated as a successful result.
        path=tmp_path/'runtime/quality/local'/ids['local']/'inputs.json'
        changed=json.loads(path.read_text()); changed['dataset']['version']='changed';path.write_text(json.dumps(changed))
        assert client.get(f"/reports/quality/{ids['local']}").status_code == 409


def test_quality_positive_filter_label_tampering_and_symlinks(tmp_path, monkeypatch):
    from copy import deepcopy
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    data = dataset(); second = deepcopy(data['cases'][0]); second.update(id='second', period='2026-02')
    data['cases'].append(second); frozen=freeze(data); ratings=labels(frozen)
    folder=tmp_path/'runtime/quality/sample'/str(uuid4());folder.mkdir(parents=True)
    (folder/'inputs.json').write_text(json.dumps(frozen));(folder/'labels.json').write_text(json.dumps(ratings))
    app=FastAPI();app.include_router(report_router(config.Settings(_env_file=None,data_mode='sample',llm_mode='fake')))
    url=f'/reports/quality/{folder.name}'
    with TestClient(app) as client:
        assert client.get(url).json()['readiness']['cases']==2
        report=client.get(url+'?period=2026-02&region=sample-region&methodology=provisional-v1').json()
        assert report['readiness']['cases']==1 and report['readiness']['reference_items']==2
        assert report['cases'][0]['id']=='second'
        ratings['dataset_hash']='tampered';(folder/'labels.json').write_text(json.dumps(ratings))
        assert client.get(url).status_code==409
        (folder/'labels.json').rename(folder/'saved-labels.json')
        (folder/'labels.json').symlink_to(folder/'saved-labels.json')
        assert client.get(url).status_code==409


def test_imported_classification_scores_are_computed_and_filtered(tmp_path,monkeypatch):
    from test_quality_metrics import fixture
    frozen,ratings,predictions=fixture((1,2,4,5),(1,4,None,5))
    monkeypatch.setattr(config,'ROOT',tmp_path)
    folder=tmp_path/'runtime/quality/sample'/str(uuid4());folder.mkdir(parents=True)
    for name,body in [('inputs',frozen),('labels',ratings),('predictions',predictions)]:
        (folder/f'{name}.json').write_text(json.dumps(body))
    app=FastAPI();app.include_router(report_router(config.Settings(_env_file=None,data_mode='sample',llm_mode='fake')))
    with TestClient(app) as client:
        url=f'/reports/quality/{folder.name}'
        report=client.get(url).json()
        assert report['classification']['groups'][0]['macro_f1']==.5 and report['status']=='partial'
        assert client.get(url+'?region=none').json()['classification']['groups']==[]
        predictions['dataset_hash']='changed';(folder/'predictions.json').write_text(json.dumps(predictions))
        assert client.get(url).status_code==409
