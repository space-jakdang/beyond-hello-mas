from copy import deepcopy
import pytest
from tests.test_graph import service,scenario
from tests.test_regional_task import task
from backend.policy.design_contracts import Analogue


def proposal(service):
    from tests.test_workflow_agents import run_task
    run=run_task(service)
    p=deepcopy(service.approval(run.id)['proposal'])
    from backend.tools.regional_resources import policy_gap
    for a in p['assignments']:
        a.update(shortfall=3,catalog_filter_performed=True,recommendations=[],uncovered_needs=a['needs'])
        a['policy_gap']=policy_gap(a)
    p['policy_research']={'status':'no_verified_candidates','candidates':[],
        'search_complete_within_scope':True,'search_scope':{'scopes':['central','seoul','gangnam'],'query':'관계','page':1},
        'coverage':{'fetched_at':'2026-10-22T00:00:00Z'}}
    return run,p


def evidence():
    a=Analogue(policy_id='other-policy',title='타 지역 관계 지원',scope='chuncheon',source_url='https://example.org/official',checked_at='2026-10-22T00:00:00Z',fields={'title':'타 지역 관계 지원','support':'방문 지원'})
    return {'status':'evidence_available','analogues':[{'source':a.model_dump(),'comparison':{'target_group_fit':'not_established'}}]}


def test_design_uses_tool_sources_and_replays_without_calls(service,monkeypatch):
    run,p=proposal(service);service.settings.llm_max_calls=10;tools=[]
    def tool(name,args):
        tools.append((name,args));return evidence()
    monkeypatch.setattr(service.policy_agent,'call_tool',tool)
    result=service.policy_designer.run(run.id,'2026-10-22T00:00:00Z',p)
    assert result['status']=='draft' and len(tools)==1 and tools[0][0]=='policy_analogues'
    assert result['draft']['citations'][0]['quote']=='타 지역 관계 지원'
    assert not result['draft']['budget_confirmed'] and not result['allocation_performed']
    assert result['approval_meaning']=='policy_review_only_not_budget_or_implementation'
    monkeypatch.setattr(service.agents,'call',lambda *args:pytest.fail('saved result must not call model'))
    assert service.policy_designer.run(run.id,'2026-10-22T00:00:00Z',p)==result
    assert len(tools)==1


def test_incomplete_search_never_invokes_designer_tools(service,monkeypatch):
    run,p=proposal(service);p['policy_research']['search_complete_within_scope']=False
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:pytest.fail('incomplete gap'))
    monkeypatch.setattr(service.agents,'call',lambda *args:pytest.fail('incomplete gap'))
    assert service.policy_designer.run(run.id,'2026-10-22T00:00:00Z',p)['status']=='needs_evidence'


def test_invented_quote_is_rejected_and_no_allocation(service,monkeypatch):
    import backend.agents.llm as llm
    run,p=proposal(service);service.settings.llm_max_calls=10
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:evidence())
    original=llm.fake
    def fake(role,payload):
        result=original(role,payload)
        if role=='policy_design' and result.get('draft'):result['draft']['citations'][0]['quote']='invented'
        return result
    monkeypatch.setattr(llm,'fake',fake)
    result=service.policy_designer.run(run.id,'2026-10-22T00:00:00Z',p)
    assert result['status']=='needs_evidence' and not result.get('draft')


def test_checkpoint_reuses_observation_after_model_interruption(service,monkeypatch):
    run,p=proposal(service);service.settings.llm_max_calls=10;count=[]
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:(count.append(1) or evidence()))
    original=service.agents.call
    def crash(run_id,sim,role,payload):
        if role=='policy_design' and payload['observation']:raise KeyboardInterrupt()
        return original(run_id,sim,role,payload)
    monkeypatch.setattr(service.agents,'call',crash)
    with pytest.raises(KeyboardInterrupt):service.policy_designer.run(run.id,'2026-10-22T00:00:00Z',p)
    monkeypatch.setattr(service.agents,'call',original)
    assert service.policy_designer.run(run.id,'2026-10-22T00:00:00Z',p)['status']=='draft' and len(count)==1


def test_supervisor_adds_separate_design_report_before_approval(service,monkeypatch):
    import backend.graph as graph
    monkeypatch.setattr(graph,'load_catalog',lambda _:[])
    service.settings.llm_max_calls=10
    monkeypatch.setattr(service.policy_agent,'run',lambda *args:{'status':'no_verified_candidates','recommendations':[],
        'search_complete_within_scope':True,'search_scope':{'scopes':['gangnam'],'query':'관계','page':1},'coverage':{'fetched_at':'2026-10-22T00:00:00Z'}})
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:evidence())
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',policy_proposal_version='legacy',task=task().model_dump(mode='json'),research_gaps=True))
    p=service.approval(run.id)['proposal']
    assert run.status=='awaiting_approval' and p['policy_design']['status']=='draft'
    assert all(not a['recommendations'] for a in p['assignments'])
    assert any(t['agent']=='policy_design' for t in service.store.traces(run.id))


def test_large_sources_keep_model_view_bounded_and_full_record(service,monkeypatch):
    import json
    from backend.policy.designer import DesignDecision
    from backend.agents.llm import PROMPTS
    run,p=proposal(service);service.settings.llm_max_calls=10;tool=evidence()
    for key in ('support','eligibility','criteria','deadline'):tool['analogues'][0]['source']['fields'][key]='공식 근거 '*1000
    tool['analogues']=[deepcopy(tool['analogues'][0]) for _ in range(5)]
    for i,a in enumerate(tool['analogues']):a['source']['policy_id']=str(i)
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:tool)
    original=service.agents.call;lengths=[]
    def call(run_id,sim,role,payload):
        if role=='policy_design':
            encoded=json.dumps({'prompt':(PROMPTS/'policy_design.txt').read_text(),'payload':payload,'schema':DesignDecision.model_json_schema()},ensure_ascii=False).encode()
            lengths.append(len(encoded))
            assert len(encoded)<=service.settings.llm_max_input_bytes
        return original(run_id,sim,role,payload)
    monkeypatch.setattr(service.agents,'call',call)
    result=service.policy_designer.run(run.id,'2026-10-22T00:00:00Z',p)
    assert result['status']=='draft', (result,lengths)
    assert len(result['analogues'][0]['fields']['support'])>400
