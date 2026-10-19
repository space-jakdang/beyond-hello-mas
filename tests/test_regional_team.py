import pytest
from backend.agents.regional_team import prepare, advance, finish
from tests.test_graph import service,scenario,decide,counts


def test_lookup_revision_survives_crash_before_checkpoint(service,monkeypatch):
    original=service.regional_step;crashed=False
    def crash(state,action):
        nonlocal crashed
        output=original(state,action)
        if action=='lookup' and not crashed:
            crashed=True
            raise KeyboardInterrupt('simulated process exit after tool trace')
        return output
    monkeypatch.setattr(service,'regional_step',crash)
    run=service.register(scenario('monthly',ym='2025-09',collaboration=True,verify_sources=True))
    with pytest.raises(KeyboardInterrupt):service.drive(run.id)
    monkeypatch.setattr(service,'regional_step',original)
    assert service.drive(run.id).status=='awaiting_approval'
    proposal=service.approval(run.id)['proposal'];team=proposal['collaboration']
    assert team['status']=='reviewed' and team['calls']==4
    assert len(team['requests'])==len(team['retrieved'])==1
    assert len(team['rounds'])==2 and team['rounds'][0]['plan']!=team['rounds'][1]['plan']
    traces=service.store.traces(run.id,limit=1000)
    assert sum(t['kind']=='llm_call' for t in traces)==4
    assert sum(t['kind']=='agent_message' and 'results' in t['payload'] for t in traces)==1
    assert counts(service,run.id)[0]==0
    assert decide(service,run.id).status=='completed'
    assert counts(service,run.id)[0]==1


def test_budget_and_deadline_never_publish_unreviewed_plan(service):
    service.settings.llm_max_calls=2
    run=service.start(scenario('monthly',ym='2025-09',collaboration=True,verify_sources=True))
    team=service.approval(run.id)['proposal']['collaboration']
    assert team['status']=='needs_human' and team['plan'] is None and team['reason']=='call_limit'
    assert counts(service,run.id)[0]==0
    state=prepare({'facts':[{'id':'a'}]}, {}, timeout_seconds=-1)
    state=advance(state,'analyze',None,'r','t',lambda *a:None)
    assert finish(state)['reason']=='deadline' and state['calls']==0


def test_unavailable_lookup_and_invalid_target_require_human():
    for target,reason in [('a','evidence_unavailable'),('outside','ValueError')]:
        state=prepare({'facts':[{'id':'a'}]}, {})
        state.update(next='regional_lookup',requests=[{'targets':[target],'reason':'source missing'}])
        state=advance(state,'lookup',None,'r','t',lambda *a:None)
        assert finish(state)['reason']==reason and state['plan'] is None


def test_analyst_can_request_lookup_and_model_failure_is_typed(service,monkeypatch):
    import backend.agents.llm as module
    original=module.fake
    def model(role,payload):
        if role=='regional_planner' and not payload['retrieved']:
            return {'action':'lookup','targets':[payload['observations']['facts'][0]['id']],'reason':'verify source','plan':None}
        return original(role,payload)
    monkeypatch.setattr(module,'fake',model)
    run=service.start(scenario('monthly',ym='2025-09',collaboration=True))
    result=service.approval(run.id)['proposal']['collaboration']
    assert result['status']=='reviewed' and result['calls']==3
    assert result['requests'][0]['sender']=='regional_analyst'
    def failed(role,payload):raise RuntimeError('PRIVATE_FAILURE_DETAIL')
    monkeypatch.setattr(module,'fake',failed)
    run=service.start(scenario('monthly',ym='2025-09',collaboration=True))
    result=service.approval(run.id)['proposal']['collaboration']
    assert result['status']=='needs_human' and result['reason']=='ValueError'
    assert 'PRIVATE_FAILURE_DETAIL' not in str(service.store.traces(run.id,limit=1000))
