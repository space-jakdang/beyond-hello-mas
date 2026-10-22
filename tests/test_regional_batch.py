from uuid import uuid4
import pytest
from backend.regional_batch import BatchRequest,create,execute,public,read
from tests.test_graph import service


def request(**updates):
    return BatchRequest.model_validate({'request_id':str(uuid4()),'task':{'sgg':'11230','ym':'2025-09','as_of':'2026-10-23'},**updates})


def test_batch_snapshot_scope_replay_and_conflict(service,monkeypatch):
    req=request();body=create(service,req)
    assert len(body['children'])==8
    with service.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM regional_batch_children').fetchone()[0]==8
    monkeypatch.setattr('backend.regional_batch.load_segments',lambda *_: (_ for _ in ()).throw(ValueError('source changed')))
    assert create(service,req)==body
    with pytest.raises(ValueError):create(service,req.model_copy(update={'sex':'F'}))
    execute(service,body['id'])
    output=public(service,read(service,body['id']))
    assert output['finished']==8
    assert all(c['status']=='awaiting_approval' for c in output['children'])
    with service.store.connection() as db:before=db.execute('SELECT COUNT(*) FROM llm_calls').fetchone()[0]
    execute(service,body['id'])
    with service.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM llm_calls').fetchone()[0]==before


def test_batch_cancel_and_unknown_scope(service):
    body=create(service,request(sex='F'))
    assert len(body['children'])==4
    with service.store.connection(write=True) as db:
        import json
        body['cancelled']=True;db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(body),body['id']))
    execute(service,body['id'])
    assert public(service,body)['status']=='cancelled'
    assert all(service.store.get_run(c['run_id']).status=='pending' for c in body['children'])
    with pytest.raises(ValueError):create(service,request(task={'sgg':'11230','ym':'2025-09','as_of':'2026-10-23','dong_cd':'11230999'}))


def test_parent_budget_is_shared_across_children(service):
    body=create(service,request());first,second=[c['run_id'] for c in body['children'][:2]]
    with service.store.connection(write=True) as db:
        db.execute('INSERT INTO llm_calls VALUES (?,?,?,?,?,?)',(first,'used','workflow_analyst','error',1.0,'{}'))
    service.agents.settings=service.settings.model_copy(update={'llm_mode':'live','openai_model':'test-model','llm_budget_usd':20,'llm_run_budget_usd':1,'input_usd_per_million':1,'output_usd_per_million':1,'price_version':'test'})
    with pytest.raises(ValueError,match='cost budget'):
        service.agents.call(second,'2026-10-23T00:00:00Z','workflow_analyst',{})


def test_missing_cohort_is_not_relabelled_as_failed(service,monkeypatch):
    from backend.tools.segments_v3 import load_segments
    rows,metadata=load_segments(service.settings)
    monkeypatch.setattr('backend.regional_batch.load_segments',lambda *_:([r for r in rows if r.sex=='M'],metadata))
    body=create(service,request())
    assert sum(c.get('status')=='no_observation' for c in body['children'])==4
    assert len([c for c in body['children'] if c['run_id']])==4


def test_cancel_api_marks_unstarted_runs_terminal(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.regional_batch import router
    body=create(service,request())
    app=FastAPI();app.include_router(router(service))
    response=TestClient(app).post('/regional/batches/'+body['id']+'/cancel')
    assert response.status_code==200
    assert all(c['status']=='cancelled' for c in response.json()['children'])
    assert service.drive(body['children'][0]['run_id']).status=='cancelled'
