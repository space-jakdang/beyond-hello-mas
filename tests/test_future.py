from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.future import FutureRequest,create_batch,future_router,future_months,scenario_rows
from backend.tools.regional_task import RegionalTask,assess
from backend.tools.regional_statistics import trend,source_check
from tests.test_graph import service,counts


def setup(service):
    app=FastAPI();app.include_router(future_router(service))
    return TestClient(app)


def request(sgg='11230'):
    return FutureRequest(request_id=uuid4(),sgg=sgg)


def task(batch,index=0,**changes):
    return RegionalTask(future_id=batch['id'],sgg=batch['sgg'],sex='M',age_group='youth',
                        ym=batch['months'][index],as_of=batch['as_of'],**changes)


def test_frozen_future_is_separate_reproducible_and_scoped(service):
    setup(service)
    path=service.settings.data_dir/'segments-v3.parquet';original=path.read_bytes()
    batch=create_batch(service,request());other=create_batch(service,request())
    assert batch['input_hash']==other['input_hash']
    assert path.read_bytes()==original
    assert future_months(date(2026,12,31))==['2027-01','2027-02','2027-03']
    result=assess(service.settings,task(batch))
    assert result['metadata']['synthetic_future'] and result['metadata']['synthetic_signals_applied']
    assert all(r['ym']==batch['months'][0] for r in result['segments'])
    assert all(r['status'] in ('synthetic_scenario','missing') for r in source_check(result)['items'])
    series=trend(service.settings,result)
    assert series['synthetic_future'] and not series['forecast']
    assert all(len(s['points'])==1 for s in series['series'])
    assert all(len(s['points'])==3 for s in trend(service.settings,assess(service.settings,task(batch,2)))['series'])
    changed=task(batch).model_copy(update={'sex':'F'})
    with pytest.raises(ValueError,match='frozen'):scenario_rows(service.settings,changed)
    with pytest.raises(ValueError):RegionalTask(sgg='11230',sex='M',age_group='youth',ym=batch['months'][0],as_of=batch['as_of'])


def test_atomic_idempotent_queue_recovers_without_approval(service):
    setup(service);req=request()
    with ThreadPoolExecutor(max_workers=3) as pool:
        batches=list(pool.map(lambda _:create_batch(service,req),range(3)))
    assert len({json.dumps(b['periods']) for b in batches})==1
    batch=batches[0]
    assert all(service.store.get_run(p['run_id']).status=='pending' for p in batch['periods'])
    service.recover()
    for p in batch['periods']:
        assert service.store.get_run(p['run_id']).status=='awaiting_approval'
        assert counts(service,p['run_id'])==(0,1)
        proposal=service.approval(p['run_id'])['proposal']
        assert proposal['assessment']['metadata']['synthetic_future']
        assert proposal['workflow']['statistics']['status']=='reviewed'
    with service.store.connection() as db:before=db.execute('SELECT count(*) FROM llm_calls').fetchone()[0]
    service.recover()
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0]==3
        assert db.execute('SELECT count(*) FROM llm_calls').fetchone()[0]==before
    with pytest.raises(ValueError):create_batch(service,req.model_copy(update={'sgg':'32010'}))
    service.settings.llm_mode='live'
    with pytest.raises(ValueError,match='mode'):create_batch(service,req)


def test_http_future_contract_and_missing_baseline(service,monkeypatch):
    client=setup(service);req=request('32010').model_dump(mode='json')
    response=client.post('/future/batches',json=req)
    assert response.status_code==202
    body=client.get('/future/batches/'+req['request_id']).json()
    assert body['synthetic'] and 'inputs' not in body and 'signals' not in body
    assert all(p['status']=='awaiting_approval' for p in body['periods'])
    assert client.post('/future/batches',json=req).json()['periods']==body['periods']
    assert client.post('/future/batches',json={**req,'sgg':'99999'}).status_code==422
    assert client.get('/future/batches/'+str(uuid4())).status_code==404
    monkeypatch.setattr('backend.future.load_segments',lambda _: ([],{}))
    assert client.post('/future/batches',json=request().model_dump(mode='json')).status_code==422


def test_queue_rollback_and_failed_period_is_not_retried(service,monkeypatch):
    setup(service)
    with service.store.connection() as db:
        db.execute("CREATE TRIGGER reject_future BEFORE INSERT ON workflows BEGIN SELECT RAISE(ABORT, 'test interruption'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):create_batch(service,request())
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM future_batches').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0]==0
        db.execute('DROP TRIGGER reject_future')
    batch=create_batch(service,request());identifier=batch['periods'][0]['run_id']
    with service.store.connection(write=True) as db:service.update_run(db,identifier,status='failed',error='test interruption')
    service.recover()
    assert service.store.get_run(identifier).status=='failed'
    assert service.store.traces(identifier)==[]
    assert all(service.store.get_run(p['run_id']).status=='awaiting_approval' for p in batch['periods'][1:])
