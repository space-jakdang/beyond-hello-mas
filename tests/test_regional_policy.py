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
    assert research['status']=='completed' and len(research['candidates'])==1
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
