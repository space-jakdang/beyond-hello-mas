import pytest
from tests.test_graph import service,scenario,counts
from tests.test_regional_task import task


def run_task(service):
    return service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))


def test_statistics_tool_observation_enters_review_and_approval(service):
    run=run_task(service)
    assert run.status=='awaiting_approval'
    p=service.approval(run.id)['proposal']
    assert p['assessment']['metadata']['statistics_version']=='2'
    assert p['workflow']['statistics']['status']=='reviewed'
    assert p['workflow']['statistics']['observations'][0]['tool']=='trend'
    assert p['snapshot_version'] and counts(service,run.id)[0]==0
    assert p['workflow']['statistics']['summary']['total']==len(p['assessment']['segments'])


def test_budget_holds_and_checkpoint_reuses_calls(service,monkeypatch):
    original=service.workflow_statistics;crashed=False
    def crash(state):
        nonlocal crashed
        result=original(state)
        if not crashed:crashed=True;raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(service,'workflow_statistics',crash)
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    with pytest.raises(KeyboardInterrupt):service.drive(run.id)
    monkeypatch.setattr(service,'workflow_statistics',original)
    import backend.agents.workflow as workflow_module
    monkeypatch.setattr(workflow_module,'run_tool',lambda *args: (_ for _ in ()).throw(AssertionError('tool must be replayed')))
    assert service.drive(run.id).status=='awaiting_approval'
    traces=service.store.traces(run.id,limit=1000)
    assert sum(t['kind']=='llm_call' for t in traces) in (3,4)
    assert sum(t['kind']=='agent_message' and 'observation' in t['payload'] for t in traces)==1
    service.settings.llm_max_calls=1
    held=run_task(service)
    assert service.approval(held.id)['proposal']['workflow']['status']=='needs_human'


def test_unobserved_statistics_ids_are_rejected(service,monkeypatch):
    import backend.agents.llm as module
    original=module.fake
    def fake(role,payload):
        response=original(role,payload)
        if role=='workflow_statistics':response['blocked_evidence_ids']=['unobserved']
        return response
    monkeypatch.setattr(module,'fake',fake)
    run=run_task(service)
    assert service.approval(run.id)['proposal']['workflow']['statistics']['status']=='needs_human'


def test_statistics_revision_removes_unassessable_priorities(service,monkeypatch):
    import backend.tools.regional_task as module
    original=module.assess
    def missing(*args):
        result=original(*args);result['segments'][0].update(value=None,stage=None)
        return result
    monkeypatch.setattr(module,'assess',missing)
    service.settings.llm_max_calls=6
    run=run_task(service);workflow=service.approval(run.id)['proposal']['workflow']
    stats=workflow['statistics']
    assert stats['status']=='reviewed' and stats['revised_plan']
    assert not set(workflow['analysis']['priority_evidence_ids'])&set(stats['blocked_evidence_ids'])


def test_matching_replay_and_catalog_failure_preserve_evidence(service,monkeypatch):
    original=service.workflow_match
    def crash(state):
        original(state)
        raise KeyboardInterrupt()
    monkeypatch.setattr(service,'workflow_match',crash)
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    with pytest.raises(KeyboardInterrupt):service.drive(run.id)
    calls=lambda:sum(t['kind']=='llm_call' for t in service.store.traces(run.id,limit=1000))
    before=calls()
    monkeypatch.setattr(service,'workflow_match',original)
    assert service.drive(run.id).status=='awaiting_approval' and calls()==before
    import backend.graph as module
    monkeypatch.setattr(module,'load_catalog',lambda *args: (_ for _ in ()).throw(OSError('unavailable')))
    held=service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json'),research_gaps=True))
    proposal=service.approval(held.id)['proposal']
    assert proposal['assignments'] and all(not r['recommendations'] for r in proposal['assignments'])
    assert 'policy_research' not in proposal


def test_both_roles_receive_stage_meaning_and_source_limits(service,monkeypatch):
    original=service.agents.call;seen=[]
    def call(run_id,sim_ts,role,payload):
        if role in ('workflow_analyst','workflow_statistics'):
            context=payload['methodology'];seen.append(role)
            assert context['stage_meanings'][5]=='집중 검토'
            assert context['group_definition']=='19–34'
            assert context['provisional'] is True
            assert 'flags' in payload['facts'][0] and 'stage' in payload['facts'][0]
            assert 'unvalidated' in context['stage_scope']
        return original(run_id,sim_ts,role,payload)
    monkeypatch.setattr(service.agents,'call',call)
    run=run_task(service)
    assert run.status=='awaiting_approval'
    assert set(seen)=={'workflow_analyst','workflow_statistics'}
