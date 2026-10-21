import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app import config
from backend.app.quality_jobs import QualityJobs,quality_job_router
from backend.events import EventStore
from test_quality_metrics import fixture


def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'ROOT',tmp_path);settings=config.Settings(_env_file=None,data_mode='sample',llm_mode='fake')
    f,l,p=fixture((1,4),(1,None));folder=tmp_path/'runtime/quality/sample'/str(uuid4());folder.mkdir(parents=True)
    for name,body in [('inputs',f),('labels',l),('predictions',p)]: (folder/f'{name}.json').write_text(json.dumps(body))
    store=EventStore(settings.runtime_dir/'events.sqlite3');jobs=QualityJobs(store,settings)
    return jobs,folder


def test_duplicate_requests_and_workers_save_once_without_private_labels(tmp_path,monkeypatch):
    jobs,folder=setup(tmp_path,monkeypatch)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:jobs.register(folder.name,'sample','deterministic'),range(2)))
    assert results[0]['id']==results[1]['id'];identifier=results[0]['id']
    with ThreadPoolExecutor(2) as pool:list(pool.map(jobs.execute,[identifier,identifier]))
    result=jobs.public(jobs.get(identifier))
    assert result['status']=='completed' and result['result']['classification']['groups'][0]['priority_recall']==0
    assert 'snapshot' not in result and 'reviewers' not in json.dumps(result)
    assert len(jobs.history(folder.name,'sample'))==1
    # Original file changes do not change the saved snapshot or its result.
    (folder/'labels.json').write_text('{}')
    assert jobs.get(identifier)['result']['readiness']['independent_resolved']==2


def test_restart_keeps_failure_and_does_not_retry(tmp_path,monkeypatch):
    jobs,folder=setup(tmp_path,monkeypatch);job=jobs.register(folder.name,'sample','deterministic')
    restarted=QualityJobs(jobs.store,jobs.settings);restarted.recover();restarted.execute(job['id'])
    failed=restarted.get(job['id']);assert failed['status']=='failed' and failed['error']=='interrupted_no_automatic_retry'
    assert restarted.register(folder.name,'sample','deterministic')['id']==job['id']


def test_api_missing_references_is_not_success_score_and_paid_mode_blocked(tmp_path,monkeypatch):
    jobs,folder=setup(tmp_path,monkeypatch)
    labels=json.loads((folder/'labels.json').read_text());labels['judgments']=[];(folder/'labels.json').write_text(json.dumps(labels))
    app=FastAPI();app.include_router(quality_job_router(jobs))
    with TestClient(app) as client:
        url=f'/reports/quality/{folder.name}'
        assert not client.get(url+'/preflight?source=sample').json()['grounding_available']
        assert client.post(url+'/jobs?source=sample',json={'suite':'grounding'}).status_code==409
        response=client.post(url+'/jobs?source=sample',json={'suite':'deterministic'});assert response.status_code==202
        result=client.get('/quality-jobs/'+response.json()['id']).json()
        assert result['status']=='completed' and result['result']['status']=='not_evaluated'
        assert client.post(url+'/jobs?source=sample',json={'suite':'deterministic'}).status_code==200
        assert result['result']['classification']['groups'][0]['macro_f1'] is None
        assert client.get('/quality-jobs/'+str(uuid4())).status_code==404
        assert client.get('/reports/quality/not-uuid/preflight').status_code==422


def test_worker_failure_is_saved_and_source_mode_is_separate(tmp_path,monkeypatch):
    jobs,folder=setup(tmp_path,monkeypatch);job=jobs.register(folder.name,'sample','deterministic')
    monkeypatch.setattr('backend.app.quality_jobs.quality_body',lambda *a:(_ for _ in ()).throw(RuntimeError('private error')))
    jobs.execute(job['id']);result=jobs.public(jobs.get(job['id']))
    assert result['status']=='failed' and result['error']=='RuntimeError' and 'private error' not in json.dumps(result)
    assert jobs.history(folder.name,'current')==[]


def test_case_evidence_matches_exact_observation_and_never_invents_reason(tmp_path,monkeypatch):
    from backend.app.quality_jobs import case_evidence
    from backend.app.contracts import Run
    from backend.events import utcnow
    from eval.quality_contracts import freeze
    jobs,folder=setup(tmp_path,monkeypatch)
    f=json.loads((folder/'inputs.json').read_text());f['dataset']['cases'][0]['facts']['evidence_id']='exact';f=freeze(f['dataset'])
    run_id=str(uuid4());jobs.store.create_run(Run(id=run_id,thread_id=run_id,scenario_id='fixture',status='completed',data_mode='sample',llm_mode='fake',input_version='1',rule_version='1',model_version='1',prompt_version='1',catalog_version='1',started_at=utcnow()))
    for name in ('inputs','labels','predictions'):
        body=f if name=='inputs' else json.loads((folder/f'{name}.json').read_text());body['dataset_hash']=f['dataset_hash']
        if name=='predictions':body['predictions'][0]['run_id']=run_id
        (folder/f'{name}.json').write_text(json.dumps(body))
    with jobs.store.connection() as db:
        db.execute('CREATE TABLE approvals (run_id TEXT, proposal TEXT)')
        db.execute('INSERT INTO approvals VALUES (?,?)',(run_id,json.dumps({'assignments':[{'evidence_id':'different','recommendations':[{'id':'wrong'}]},{'evidence_id':'exact','recommendations':[{'id':'right'}]}]})))
    result=case_evidence(jobs,folder.name,'0','sample')
    assert result['rows'][0]['selected_ids']==['right'] and result['rows'][0]['decision_evidence'] is None


def test_paid_job_duplicate_never_calls_judge_twice(tmp_path,monkeypatch):
    jobs,folder=setup(tmp_path,monkeypatch)
    jobs.settings=jobs.settings.model_copy(update={'llm_mode':'live','openai_model':'test','input_usd_per_million':1.0,'output_usd_per_million':1.0,'price_version':'test','llm_budget_usd':20.0})
    monkeypatch.setattr('backend.app.quality_jobs.find_spec',lambda _:True)
    # A recorded live context is required even though the judge itself is mocked.
    predictions=json.loads((folder/'predictions.json').read_text());predictions['predictions'][0]['run_id']='recorded';(folder/'predictions.json').write_text(json.dumps(predictions))
    with jobs.store.connection() as db:
        db.execute('CREATE TABLE llm_calls (run_id TEXT,status TEXT,role TEXT,body TEXT,reserve_usd REAL)')
        db.execute('INSERT INTO llm_calls VALUES (?,?,?,?,?)',('recorded','ok','workflow_analyst',json.dumps({'mode':'live'}),.1))
    import eval.run_grounding
    calls=[]
    async def failed(*args):calls.append(True);raise RuntimeError('provider private body')
    monkeypatch.setattr(eval.run_grounding,'evaluate',failed)
    first=jobs.register(folder.name,'current','grounding');jobs.execute(first['id'])
    second=jobs.register(folder.name,'current','grounding');jobs.execute(second['id'])
    assert first['id']==second['id'] and len(calls)==1
    assert jobs.get(first['id'])['status']=='failed'


def test_comparison_key_changes_for_labels_and_judge_settings(tmp_path,monkeypatch):
    jobs,folder=setup(tmp_path,monkeypatch)
    first=jobs.register(folder.name,'sample','deterministic')
    labels=json.loads((folder/'labels.json').read_text());labels['judgments']=[];(folder/'labels.json').write_text(json.dumps(labels))
    second=jobs.register(folder.name,'sample','deterministic')
    assert first['comparison_key']!=second['comparison_key']
    monkeypatch.setattr(jobs,'preflight',lambda *args:{'grounding_available':True})
    jobs.settings=jobs.settings.model_copy(update={'openai_model':'judge-a'})
    third=jobs.register(folder.name,'current','grounding')
    jobs.settings=jobs.settings.model_copy(update={'openai_model':'judge-b'})
    fourth=jobs.register(folder.name,'current','grounding')
    assert third['comparison_key']!=fourth['comparison_key'] and fourth['judge_model']=='judge-b'
