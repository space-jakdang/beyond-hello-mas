import pytest
from backend.revisions import request_revision
from tests.test_graph import service,decide,counts
from tests.test_workflow_agents import run_task


def revise(service,run,reason='통계 근거를 보완해 주세요.'):
    snapshot=service.approval(run.id)['approval']['snapshot_version']
    return request_revision(service,run.id,snapshot,'담당자',reason)


def test_revision_is_atomic_idempotent_and_requires_new_approval(service):
    run=run_task(service);child=revise(service,run)
    assert revise(service,run).id==child.id
    assert service.store.get_run(run.id).status=='rejected'
    assert counts(service,run.id)[0]==0
    assert service.drive(child.id).status=='awaiting_approval'
    proposal=service.approval(child.id)['proposal']
    traces=service.store.traces(child.id,limit=1000)
    analyst=next(t for t in traces if t['kind']=='llm_call' and t['payload'].get('role')=='workflow_analyst')
    assert analyst['payload']['input']['feedback']['reason']=='통계 근거를 보완해 주세요.'
    assert proposal['revision']['parent_run_id']==run.id
    assert proposal['snapshot_version']!=service.approval(run.id)['proposal']['snapshot_version']
    with pytest.raises(ValueError):revise(service,run,'다른 요청')
    assert decide(service,child.id).status=='completed'
    with pytest.raises(ValueError):revise(service,child)


def test_stale_request_and_bounded_revision_depth(service):
    run=run_task(service)
    with pytest.raises(ValueError):request_revision(service,run.id,'stale','담당자','보완')
    first=revise(service,run);service.drive(first.id)
    second=revise(service,first);service.drive(second.id)
    with pytest.raises(ValueError):revise(service,second)


def test_revision_rollback_leaves_parent_pending(service,monkeypatch):
    run=run_task(service)
    original=service.once
    def fail(db,state,name,*args):
        if name=='revision':raise RuntimeError('transaction interrupted')
        return original(db,state,name,*args)
    monkeypatch.setattr(service,'once',fail)
    with pytest.raises(RuntimeError):revise(service,run)
    assert service.approval(run.id)['approval']['status']=='pending'
    with service.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1


def test_revision_http_contract_and_linked_overview(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.graph_routes import graph_router
    app=FastAPI();app.include_router(graph_router(service));client=TestClient(app)
    run=run_task(service)
    body={'snapshot_version':service.approval(run.id)['approval']['snapshot_version'],'operator':'담당자','reason':'재검토'}
    response=client.post(f'/runs/{run.id}/revision',json=body)
    assert response.status_code==202
    child=response.json()['id']
    assert client.get(f'/runs/{run.id}/overview').json()['revision']['child_run_id']==child
    assert client.get(f'/runs/{child}/overview').json()['revision']['parent_run_id']==run.id
    assert client.post(f'/runs/{run.id}/revision',json=body).json()['id']==child
    assert client.post(f'/runs/{run.id}/revision',json={**body,'reason':'x'*1001}).status_code==422


def test_revision_commit_is_coherent_before_resume(service,monkeypatch):
    run=run_task(service)
    execute=service.execute
    monkeypatch.setattr(service,'execute',lambda _:None)
    child=revise(service,run)
    assert service.store.get_run(run.id).status=='rejected'
    assert service.approval(run.id)['approval']['status']=='rejected'
    assert service.store.get_run(child.id).status=='running'
    monkeypatch.setattr(service,'execute',execute)
    service.recover()
    assert service.store.get_run(child.id).status=='awaiting_approval'
    assert counts(service,run.id)[0]==0


def test_concurrent_revisions_share_one_child(service):
    from concurrent.futures import ThreadPoolExecutor
    run=run_task(service)
    with ThreadPoolExecutor(max_workers=3) as pool:
        children=list(pool.map(lambda _:revise(service,run).id,range(3)))
    assert len(set(children))==1
