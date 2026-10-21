import pytest
from backend.policy.service import PolicyService, Search
from tests.test_policy import provider
from tests.test_graph import service,scenario,counts,decide


def test_gap_delegates_policy_without_promoting_candidates(service,monkeypatch):
    import backend.graph as module
    monkeypatch.setattr(module,'load_catalog',lambda _:[])
    service.settings.llm_max_calls=6
    policies=PolicyService(service.settings,provider)
    def tool(name,args):
        if name=='policy_refresh':return policies.refresh()
        if name=='policy_search':return policies.search(Search(**args))
        if name=='policy_detail':return policies.detail(args['policy_id'])
        if name=='policy_details':return policies.details(args['policy_ids'])
        pytest.fail(name)
    monkeypatch.setattr(service.policy_agent,'call_tool',tool)
    original=service.regional_policy_node
    def crash(state):
        original(state)
        raise KeyboardInterrupt('after saved policy result')
    monkeypatch.setattr(service,'regional_policy_node',crash)
    run=service.register(scenario('monthly',ym='2025-09',collaboration=True,research_gaps=True))
    with pytest.raises(KeyboardInterrupt):service.drive(run.id)
    monkeypatch.setattr(service,'regional_policy_node',original)
    assert service.drive(run.id).status=='awaiting_approval'
    proposal=service.approval(run.id)['proposal'];research=proposal['policy_research']
    assert research['status']=='completed' and len(research['candidates'])==5
    assert not research['eligibility_verified'] and research['remaining_capacity'] is None
    assert all(not a['recommendations'] for a in proposal['assignments'])
    assert counts(service,run.id)[0]==0
    traces=service.store.traces(run.id,limit=1000)
    assert sum(t['kind']=='llm_call' for t in traces)==6
    assert service.drive(run.id).status=='awaiting_approval'
    assert service.store.traces(run.id,limit=1000)==traces
    assert decide(service,run.id).status=='completed'


def test_budget_exhaustion_is_not_a_policy_recommendation(service,monkeypatch):
    import backend.graph as module
    monkeypatch.setattr(module,'load_catalog',lambda _:[])
    service.settings.llm_max_calls=2
    monkeypatch.setattr(service.policy_agent,'run',lambda *a:pytest.fail('no remaining calls'))
    run=service.start(scenario('monthly',ym='2025-09',collaboration=True,research_gaps=True))
    result=service.approval(run.id)['proposal']['policy_research']
    assert result['status']=='call_limit' and result['candidates']==[]
    assert counts(service,run.id)[0]==0


def test_unknown_district_does_not_research_wrong_jurisdiction(service,monkeypatch):
    monkeypatch.setattr(service.policy_agent,'run',lambda *a:pytest.fail('unsupported district'))
    scenario_input=scenario('monthly',ym='2025-09',collaboration=True,research_gaps=True)
    run=service.register(scenario_input)
    output=service.regional_policy_node({'run_id':run.id,'scenario':scenario_input.model_dump(mode='json'),
        'classification':{'collaboration':{'calls':0}},'proposal':{'assignments':[{'dong_cd':'99999101','shortfall':3,'recommendations':[]}]}})
    assert output['proposal']['policy_research']['status']=='unsupported_scope'
    assert output['proposal']['policy_research']['candidates']==[]


def test_workflow_uses_configured_policy_budget_without_changing_legacy(service,monkeypatch):
    from tests.test_regional_task import task
    import backend.graph as module
    monkeypatch.setattr(module,'load_catalog',lambda _:[])
    service.settings.llm_max_calls=10
    delegated=[]
    def research(run_id,sim_ts,payload):
        with service.store.connection() as db:
            calls=db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run_id,)).fetchone()[0]
        assert payload['max_steps']==(10-calls-2 if not delegated else 6-calls)
        assert len(payload['goal'])<=1000 and '요청 집단' in payload['goal']
        delegated.append(payload)
        return {'status':'no_verified_candidates','recommendations':[],'steps':0}
    monkeypatch.setattr(service.policy_agent,'run',research)
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json'),research_gaps=True))
    assert delegated and delegated[0]['max_steps']>3
    assert '"age_group": "youth"' in delegated[0]['goal'] and '"sex": "M"' in delegated[0]['goal']
    assert '대상 연령·관할' in delegated[0]['goal']
    assert service.approval(run.id)['proposal']['policy_research']['steps']==0
    assert counts(service,run.id)[0]==0

    legacy=service.start(scenario('monthly',ym='2025-09',collaboration=True,research_gaps=True))
    assert len(delegated)==2 and delegated[1]['max_steps']<=6
    assert counts(service,legacy.id)[0]==0


@pytest.mark.parametrize('budget',[4,5,6,7,10])
def test_policy_step_budget_leaves_design_room_only_when_available(service,monkeypatch,budget):
    from tests.test_regional_task import task
    import backend.graph as module
    monkeypatch.setattr(module,'load_catalog',lambda _:[])
    service.settings.llm_max_calls=budget
    seen=[]
    def research(run_id,sim_ts,payload):
        with service.store.connection() as db:
            used=db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run_id,)).fetchone()[0]
        available=budget-used
        assert payload['max_steps']==(available-2 if available>=5 else available)
        seen.append(payload)
        return {'status':'search_incomplete','recommendations':[]}
    monkeypatch.setattr(service.policy_agent,'run',research)
    service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json'),research_gaps=True))
    assert seen
