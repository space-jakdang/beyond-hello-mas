import json
from copy import deepcopy
from uuid import uuid4
import pytest
from tests.test_graph import service,scenario
from backend.policy.alternative_review import Change,initialize,read,update,router


def sample(service):
    initialize(service.store);run=service.register(scenario())
    scope={'sgg':'11230','ym':'2025-09','as_of':'2026-10-23','target_groups':['M/youth']}
    return service.policy_designer.propose(run.id,run.id,scope,[{'dong_cd':'11230680','dong_nm':'검증동'}],[])[0]


def change(body,action='approve',index=0):
    return Change(version=body['version'],revision=body['review_revision'],alternative_id=body['alternatives'][index]['id'],operator='담당자',action=action,text='현장 검토 기록')


def test_review_revision_history_and_edit_resets_all_without_touching_evidence(service):
    body=sample(service);owner=body['owner_id'];dong=body['dong_cd']
    approved=update(service.store,owner,dong,change(body))
    assert approved['alternatives'][0]['review_status']=='approved'
    assert not approved['budget_approved'] and not approved['allocation_performed']
    with pytest.raises(ValueError):update(service.store,owner,dong,change(body))
    edited=update(service.store,owner,dong,change(approved,'edit',1))
    assert all(a['review_status']=='pending' for a in edited['alternatives'])
    assert edited['evidence']==body['evidence'] and edited['version']==body['version']
    with service.store.connection() as db:
        assert read(db,owner,dong,0)==body
        assert read(db,owner,dong,1)==approved
        assert read(db,owner,dong,2)==edited


def test_regeneration_is_new_owner_and_idempotent_with_same_budget(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.policy.alternative_regeneration import router as regeneration_router
    from backend.policy.alternatives import router as alternative_router
    source=sample(service);app=FastAPI();app.include_router(regeneration_router(service));app.include_router(alternative_router(service.store));client=TestClient(app)
    request={'request_id':str(uuid4()),'version':source['version'],'revision':0}
    path=f"/policy-proposals/{source['owner_id']}/{source['dong_cd']}/regenerate"
    assert client.post(path,json=request).status_code==202
    new=client.get('/policy-proposals/'+request['request_id']).json()['sets'][0]
    assert new['owner_id']!=source['owner_id'] and new['review_revision']==0 and len(new['alternatives'])==3
    assert client.post(path,json=request).status_code==202
    assert client.get('/policy-proposals/'+request['request_id']).json()['sets'][0]==new
    with service.store.connection() as db:
        job=json.loads(db.execute('SELECT body FROM policy_regenerations').fetchone()[0])
        assert job['run_id']==source['owner_id']
        assert read(db,source['owner_id'],source['dong_cd'])==source


def test_regeneration_mode_mismatch_is_visible_and_recovers(service):
    from backend.policy.alternative_regeneration import router as regeneration_router,execute,recover
    source=sample(service);regeneration_router(service)
    identifier=str(uuid4());job={'id':identifier,'status':'pending','source':{**source,'llm_mode':'live'},'run_id':source['owner_id']}
    with service.store.connection(write=True) as db:db.execute('INSERT INTO policy_regenerations VALUES (?,?)',(identifier,json.dumps(job)))
    execute(service,identifier)
    with service.store.connection() as db:assert json.loads(db.execute('SELECT body FROM policy_regenerations WHERE id=?',(identifier,)).fetchone()[0])['status']=='mode_mismatch'
    job['source']['llm_mode']='fake';job['status']='mode_mismatch'
    with service.store.connection(write=True) as db:db.execute('UPDATE policy_regenerations SET body=? WHERE id=?',(json.dumps(job),identifier))
    recover(service)
    with service.store.connection() as db:assert json.loads(db.execute('SELECT body FROM policy_regenerations WHERE id=?',(identifier,)).fetchone()[0])['status']=='completed'
