from copy import deepcopy
from uuid import uuid4
import pytest
from tests.test_graph import service,scenario
from tests.test_regional_task import task
from backend.policy.alternatives import templates,validate


def sets(service,owner):
    import json
    with service.store.connection() as db:return [json.loads(r[0]) for r in db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=?',(owner,))]


def test_always_three_even_when_budget_spent_and_replay_has_no_calls(service,monkeypatch):
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    result=sets(service,run.id)
    assert result and all(len(s['alternatives'])==3 for s in result)
    assert all(not s['allocation_performed'] and not s['budget_approved'] for s in result)
    assert service.approval(run.id)['proposal']['policy_alternatives']['dong_count']==len(result)
    monkeypatch.setattr(service.agents,'call',lambda *args:pytest.fail('replay must not call'))
    first=result[0]
    assert service.policy_designer.propose(run.id,run.id,first['scope'],[{'dong_cd':first['dong_cd'],'dong_nm':first['dong_nm']}],[])==[first]


def test_empty_evidence_and_failed_model_are_explicit_concepts(service,monkeypatch):
    run=service.register(scenario());scope={'sgg':'11230','ym':'2025-09','as_of':'2026-10-23','target_groups':['M/youth','F/elderly']}
    dong={'dong_cd':'11230680','dong_nm':'검증동'}
    result=service.policy_designer.propose(run.id,run.id,scope,[dong],[])[0]
    assert result['generation_mode']=='template_fallback'
    for a in result['alternatives']:
        assert a['evidence_status']=='concept_only' and not a['citations'] and a['missing_evidence']
    context=result['evidence'];output=templates(context)
    output['alternatives'][0]['source_policy_ids']=['invented']
    with pytest.raises(ValueError,match='unknown policy'):validate(output,context)
    output=templates(context);output['alternatives'][0]['target_groups']=['outside']
    with pytest.raises(ValueError,match='unrequested'):validate(output,context)
    output=templates(context);output['alternatives'][0]['proposed_service']=output['alternatives'][1]['proposed_service']
    with pytest.raises(ValueError,match='duplicate'):validate(output,context)


def test_batch_creates_three_per_dong_not_per_cohort(service):
    from backend.regional_batch import create,execute,public,read
    from tests.test_regional_batch import request
    body=create(service,request());execute(service,body['id'])
    result=sets(service,body['id'])
    assert len(result)==len(body['dongs'])
    assert all(len(s['alternatives'])==3 and len(s['scope']['target_groups'])==8 for s in result)
    assert public(service,read(service,body['id']))['policy_proposals']['dong_count']==len(result)
    execute(service,body['id']);assert sets(service,body['id'])==result


def test_failed_known_scope_retains_three_concepts(service,monkeypatch):
    def fail(*args):raise ValueError('no observations')
    monkeypatch.setattr(service,'classify_node',fail)
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    service.execute(run.id)
    assert service.store.get_run(run.id).status=='failed'
    assert sets(service,run.id) and all(s['generation_mode']=='template_fallback' for s in sets(service,run.id))


def test_model_and_tool_failure_preserve_three_and_cancellation_stops_next_dong(service,monkeypatch):
    from tests.test_workflow_agents import run_task
    from backend.regional_batch import create,execute,read
    from tests.test_regional_batch import request
    run=run_task(service);p=service.approval(run.id)['proposal']
    rows=p['assessment']['segments'];dong={'dong_cd':rows[0]['dong_cd'],'dong_nm':rows[0]['dong_nm']}
    scope={**p['task'],'target_groups':['M/youth']}
    def fail(*args):raise RuntimeError('offline')
    monkeypatch.setattr(service.agents,'call',fail);monkeypatch.setattr(service.policy_agent,'call_tool',fail)
    result=service.policy_designer.propose(str(uuid4()),run.id,scope,[dong],[p])[0]
    assert result['generation_mode']=='template_fallback' and len(result['alternatives'])==3
    assert result['evidence']['source_search_status']=='unavailable'
    body=create(service,request());body['cancelled']=True
    import json
    with service.store.connection(write=True) as db:db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(body),body['id']))
    service.policy_designer.propose(body['id'],run.id,scope,body['dongs'],[])
    assert sets(service,body['id'])==[]


def test_invalid_alternative_does_not_discard_other_two(service,monkeypatch):
    from types import SimpleNamespace
    from tests.test_workflow_agents import run_task
    run=run_task(service);p=service.approval(run.id)['proposal'];row=next(r for r in p['assessment']['segments'] if r['value'] is not None and r['stage'] is not None)
    def call(run_id,sim,role,context):
        output=templates(context)
        for a in output['alternatives']:a['problem_evidence_ids']=[row['evidence_id']]
        output['alternatives'][0]['source_policy_ids']=['invented']
        return SimpleNamespace(model_dump=lambda:output)
    monkeypatch.setattr(service.agents,'call',call)
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:{'status':'unavailable'})
    result=service.policy_designer.propose(str(uuid4()),run.id,{**p['task'],'target_groups':[p['task']['sex']+'/'+p['task']['age_group']]},[{'dong_cd':row['dong_cd'],'dong_nm':row['dong_nm']}],[p])[0]
    assert result['generation_mode']=='mixed'
    assert [a['generation_mode'] for a in result['alternatives']]==['template_fallback','fixture','fixture']
    assert result['alternatives'][1]['evidence_status']=='partial'
