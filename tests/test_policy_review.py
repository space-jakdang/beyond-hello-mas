from copy import deepcopy
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.policy.review import PolicyReview,policy_review_router
from backend.policy.design_contracts import validate_draft
from tests.test_policy_design_contracts import fixture
from tests.test_graph import service,scenario


def setup(service):
    run=service.register(scenario('monthly'));draft,gap,sources=fixture()
    result=validate_draft(draft,['obs'],gap,sources);result['status']='draft'
    with service.store.connection(write=True) as db:db.execute('INSERT INTO policy_designs VALUES (?,?)',(run.id,json.dumps(result)))
    return run.id,PolicyReview(service.store),result


def body(document,**values):
    return {'expected_revision':0,'version':document['version'],'action':'approved','operator':'담당자','reason':'원문과 운영 전제를 검토함',**values}


def test_review_is_idempotent_versioned_and_never_resource_approval(service):
    id,review,document=setup(service)
    first=review.act(id,body(document));assert first['document']['review_status']=='approved'
    assert review.act(id,body(document))==first
    with service.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0]==0
    changed=deepcopy(document['draft']);changed['proposed_service']='담당자 수정: 방문 방식의 실현 가능성 검토'
    revised=review.act(id,body(document,expected_revision=1,action='revise',draft=changed))
    assert revised['document']['review_status']=='pending' and revised['document']['version']!=document['version']
    assert revised['history'][0]['document']['review_status']=='approved'
    assert review.get(id)==revised
    assert review.act(id,body(document))==revised  # Retry after another version never applies twice.
    with pytest.raises(ValueError):review.act(id,body(document,action='rejected'))
    bad=deepcopy(changed);bad['citations'][0]['quote']='invented'
    with pytest.raises(ValueError):review.act(id,body(revised['document'],expected_revision=2,action='revise',draft=bad))
    assert review.get(id)['revision']==2


def test_concurrent_reviews_have_one_winner(service):
    id,review,document=setup(service)
    def act(action):
        try:return review.act(id,body(document,action=action))['revision']
        except ValueError:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(act,['approved','rejected']))
    assert set(results)=={1,'conflict'} and review.get(id)['revision']==1


def test_review_api_rejects_missing_stale_and_insufficient_drafts(service):
    id,review,document=setup(service);app=FastAPI();app.include_router(policy_review_router(service.store))
    with TestClient(app) as client:
        assert client.get('/runs/missing/policy-design').status_code==404
        assert client.get(f'/runs/{id}/policy-design').json()['revision']==0
        assert client.post(f'/runs/{id}/policy-design/review',json=body(document,operator=' ')).status_code==422
        assert client.post(f'/runs/{id}/policy-design/review',json=body(document,version='old')).status_code==409
        draft=deepcopy(document['draft']);draft['status']='needs_evidence';draft['title']='근거 보완 초안'
        revised=review.act(id,body(document,action='revise',draft=draft))
        assert client.post(f'/runs/{id}/policy-design/review',json=body(revised['document'],expected_revision=1)).status_code==409
