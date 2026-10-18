import json
import shutil
from uuid import uuid4
import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.contracts import Scenario
from backend.events import EventStore
from backend.graph import GraphService
from backend.policy.agent import PolicyDecision, PolicyTask
from backend.policy.service import PolicyService, Search
from tests.test_policy import provider

SIM='2025-07-01T09:00:00+09:00'


def scenario(**payload):
    return Scenario(id='policy-test',type='policy',sim_time=SIM,payload={'goal':'지원 정책 조사',**payload})


@pytest.fixture
def graph(tmp_path,monkeypatch):
    import backend.app.config as config
    monkeypatch.setattr(config,'ROOT',tmp_path)
    settings=Settings(_env_file=None,llm_mode='fake',gov24_service_key=None)
    graph=GraphService(EventStore(settings.runtime_dir/'events.sqlite3'),settings)
    policies=PolicyService(settings,provider)
    def tool(name,args):
        if name=='policy_refresh':return policies.refresh()
        if name=='policy_search':return policies.search(Search(**args))
        if name=='policy_coverage':return policies.coverage()
        if name=='policy_detail':return policies.detail(args['policy_id'])
        raise AssertionError(name)
    monkeypatch.setattr(graph.policy_agent,'call_tool',tool)
    return graph


def result(graph,run_id):
    return next(t['payload'] for t in graph.store.traces(run_id) if t['agent']=='policy' and t['kind']=='node_end')


def test_supervisor_react_observations_and_recovery(graph):
    run=graph.start(scenario(scopes=['seoul']))
    assert run.status=='completed'
    output=result(graph,run.id)
    assert output['status']=='completed' and len(output['recommendations'])==1
    assert output['recommendations'][0]['policy']['scope']=='seoul'
    assert output['recommendations'][0]['detail_status']=='cached'
    traces=graph.store.traces(run.id)
    assert any(t['agent']=='supervisor' and t['kind']=='route' and t['payload']['worker']=='policy' for t in traces)
    calls=[t for t in traces if t['kind']=='llm_call']
    assert len(calls)==4 and calls[1]['payload']['input']['observations'][0]['result']['scopes']['seoul']==1
    assert not output['allocation_performed'] and not output['all_policies_known']
    graph.recover()
    assert graph.store.traces(run.id)==traces
    with graph.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0]==0


def test_bounds_repetition_fabricated_evidence_and_scope(graph,monkeypatch):
    limited=graph.start(scenario(max_steps=1))
    assert result(graph,limited.id)['status']=='step_limit'
    def decision(action,**kw):
        return PolicyDecision(action=action,query='',page=1,policy_id=None,recommendations=[],reason='test',**kw)
    monkeypatch.setattr(graph.agents,'call',lambda *args:decision('policy_refresh'))
    repeated=graph.start(scenario())
    assert result(graph,repeated.id)['status']=='repeated_action'
    invented=PolicyDecision(action='finish',query='',page=1,policy_id=None,reason='test',recommendations=[{
        'policy_id':'invented','field':'title','value':'fabricated','explanation':'fake'}])
    monkeypatch.setattr(graph.agents,'call',lambda *args:invented)
    invalid=graph.start(scenario())
    assert result(graph,invalid.id)['status']=='invalid_evidence'
    outside=decision('policy_detail').model_copy(update={'policy_id':'outside'})
    monkeypatch.setattr(graph.agents,'call',lambda *args:outside)
    invalid=graph.start(scenario(scopes=['seoul']))
    assert result(graph,invalid.id)['status']=='invalid_action'
    with pytest.raises(ValidationError):scenario(scopes=['other'])


def test_policy_crisis_still_uses_existing_gate(graph,monkeypatch):
    monkeypatch.setattr(graph.policy_agent,'run',lambda *args:pytest.fail('worker must not run'))
    run=graph.start(scenario(goal='지금 죽고 싶어요'))
    assert run.status=='completed'
    assert [t['agent'] for t in graph.store.traces(run.id) if t['kind']=='node_end']==['supervisor','link']


def test_scripted_model_changes_next_action_and_replays_saved_tools(graph,monkeypatch):
    inputs=[]
    graph.settings.llm_max_calls=5
    def call(run,sim,role,payload):
        inputs.append(payload)
        obs=payload['observations']
        # Missing cache leads to refresh; refreshed observations lead to a scoped search.
        action=['policy_coverage','policy_refresh','policy_coverage','policy_search','finish'][len(obs)]
        return PolicyDecision(action=action,query='없음',page=1,policy_id=None,recommendations=[],reason='fixture')
    monkeypatch.setattr(graph.agents,'call',call)
    run=graph.register(scenario())
    task=PolicyTask.model_validate(scenario().payload)
    first=graph.policy_agent.run(run.id,SIM,task)
    assert first['status']=='no_verified_candidates'
    assert inputs[1]['observations'][0]['result']['status']=='unavailable'
    assert inputs[2]['observations'][1]['result']['status']=='cached'
    assert inputs[3]['observations'][2]['result']['status']=='cached'
    monkeypatch.setattr(graph.policy_agent,'call_tool',lambda *args:pytest.fail('saved observations must not re-call tools'))
    second=graph.policy_agent.run(run.id,SIM,task)
    assert second==first


def test_real_supervisor_to_mcp_missing_credentials():
    settings=Settings(_env_file=None,llm_mode='fake',gov24_service_key=None,evaluation_id=uuid4())
    graph=GraphService(EventStore(settings.runtime_dir/'events.sqlite3'),settings)
    try:
        run=graph.start(scenario())
        output=result(graph,run.id)
        assert output['status']=='no_verified_candidates'
        assert output['coverage']['last_attempt']['reason']=='missing_credentials'
        assert not output['recommendations']
    finally:shutil.rmtree(settings.runtime_dir)


def test_exact_evidence_and_model_failure_are_safe(graph,monkeypatch):
    from backend.policy.agent import compact
    task=PolicyTask(goal='test',scopes=['seoul'])
    observation={'action':{'action':'policy_detail'},'result':{'status':'cached','policy':{
        'id':'known','scope':'seoul','title':'real','eligibility':'specific'}}}
    decision=PolicyDecision(action='finish',query='',page=1,policy_id=None,reason='test',recommendations=[{
        'policy_id':'known','field':'eligibility','value':'anyone','explanation':'wrong'}])
    with pytest.raises(ValueError,match='evidence'):
        graph.policy_agent.recommendations(decision,[observation],task)
    def failure(*args):raise ValueError('PRIVATE_PROVIDER_MESSAGE')
    monkeypatch.setattr(graph.agents,'call',failure)
    run=graph.start(scenario())
    assert result(graph,run.id)['status']=='model_unavailable_or_budget'
    assert 'PRIVATE_PROVIDER_MESSAGE' not in json.dumps(graph.store.traces(run.id))
    assert len(compact({'field':'x'*1000})['field'])==800
    assert compact({'conditions':{'JA0101':'Y'}})['conditions']=={'JA0101':'Y'}
