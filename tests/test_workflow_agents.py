import pytest
from tests.test_graph import service,scenario,counts
from tests.test_regional_task import task


def run_task(service,**changes):
    return service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task(**changes).model_dump(mode='json')))


def test_statistics_tool_observation_enters_review_and_approval(service):
    run=run_task(service,goal='월별 추이를 확인하세요.')
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
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task(goal='월별 추이를 확인하세요.').model_dump(mode='json')))
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
    assert stats['revision_check']=='final_statistics_review'
    assert [item['phase'] for item in stats['review_history']]==['initial','final']
    assert not set(workflow['analysis']['priority_evidence_ids'])&set(stats['blocked_evidence_ids'])


def test_matching_replay_and_catalog_failure_preserve_evidence(service,monkeypatch):
    original=service.workflow_match
    def crash(state):
        original(state)
        raise KeyboardInterrupt()
    monkeypatch.setattr(service,'workflow_match',crash)
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    with pytest.raises(KeyboardInterrupt):service.drive(run.id)
    calls=lambda:sum(t['kind']=='llm_call' and t['payload'].get('role')=='workflow_matching' for t in service.store.traces(run.id,limit=1000))
    before=calls()
    monkeypatch.setattr(service,'workflow_match',original)
    import backend.graph as module
    monkeypatch.setattr(module,'load_catalog',lambda *args: (_ for _ in ()).throw(OSError('unavailable')))
    assert service.drive(run.id).status=='awaiting_approval' and calls()==before==0
    assert service.approval(run.id)['proposal']['workflow']['matching']['status']=='reviewed'
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


def test_sufficient_summary_needs_no_tool_round_trip(service,monkeypatch):
    import backend.agents.workflow as module
    monkeypatch.setattr(module,'run_tool',lambda *args:pytest.fail('sufficient summary must not fetch a tool'))
    run=run_task(service);stats=service.approval(run.id)['proposal']['workflow']['statistics']
    assert stats['status']=='reviewed' and stats['observations']==[]
    assert [r['action'] for r in stats['review_history']]==['finish']
    calls=[t for t in service.store.traces(run.id,limit=1000) if t['kind']=='llm_call' and t['payload'].get('role')=='workflow_statistics']
    assert len(calls)==1


@pytest.mark.parametrize('final_action',['human','lookup','revise'])
def test_final_review_can_hold_but_cannot_start_another_loop(service,monkeypatch,final_action):
    import backend.tools.regional_task as task_module
    import backend.agents.llm as llm_module
    original_assess=task_module.assess;original_fake=llm_module.fake
    def missing(*args):
        result=original_assess(*args);result['segments'][0].update(value=None,stage=None)
        return result
    def fake(role,payload):
        result=original_fake(role,payload)
        if role=='workflow_statistics' and payload.get('review_phase')=='final':
            result.update(action=final_action,reason='수정된 해석도 근거 확인이 필요합니다.')
        return result
    monkeypatch.setattr(task_module,'assess',missing);monkeypatch.setattr(llm_module,'fake',fake)
    service.settings.llm_max_calls=8
    run=run_task(service);proposal=service.approval(run.id)['proposal'];stats=proposal['workflow']['statistics']
    assert stats['status']=='needs_human' and stats['revised_plan']
    assert proposal['workflow']['analysis']==stats['initial_plan']!=stats['revised_plan']
    assert stats.get('revision_check') is None and not any(r['recommendations'] for r in proposal['assignments'])
    assert [r['phase'] for r in stats['review_history']]==['initial','final']
    calls=[t['payload']['role'] for t in service.store.traces(run.id,limit=1000) if t['kind']=='llm_call']
    assert calls.count('workflow_analyst')==2 and calls.count('workflow_statistics')==2
    if final_action!='human':assert stats['reason']=='final_review_requires_finish_or_human'


def test_exhausted_final_review_budget_keeps_revision_unapproved(service,monkeypatch):
    import backend.tools.regional_task as module
    original=module.assess
    def missing(*args):
        result=original(*args);result['segments'][0].update(value=None,stage=None)
        return result
    monkeypatch.setattr(module,'assess',missing);service.settings.llm_max_calls=3
    run=run_task(service);proposal=service.approval(run.id)['proposal'];stats=proposal['workflow']['statistics']
    assert stats['revised_plan'] and stats['status']=='needs_human'
    assert proposal['workflow']['analysis']==stats['initial_plan']
    assert [r['phase'] for r in stats['review_history']]==['initial']
    assert stats.get('revision_check') is None and not any(r['recommendations'] for r in proposal['assignments'])


def test_summary_insights_cannot_be_requested_again_as_new_information(service,monkeypatch):
    import backend.agents.llm as llm_module
    import backend.agents.workflow as workflow_module
    original=llm_module.fake
    def fake(role,payload):
        result=original(role,payload)
        if role=='workflow_statistics':result.update(action='lookup',tool='policy_insights')
        return result
    monkeypatch.setattr(llm_module,'fake',fake)
    monkeypatch.setattr(workflow_module,'run_tool',lambda *args:pytest.fail('duplicate summary lookup'))
    run=run_task(service);stats=service.approval(run.id)['proposal']['workflow']['statistics']
    assert stats['status']=='needs_human' and stats['reason']=='statistics_duplicate_summary_lookup'
    assert not stats['observations']


def test_unversioned_review_keeps_legacy_tool_requirement(service):
    from backend.agents.workflow import analyze,statistical_review
    from backend.tools.regional_task import assess
    from time import time
    assessment=assess(service.settings,task());assessment['metadata'].pop('review_contract_version')
    assessment['metadata']['statistics_version']='2'
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    plan=analyze(service.agents,run.id,'2025-09-01',assessment)
    result=statistical_review(service.agents,service.settings,run.id,'2025-09-01',assessment,plan,lambda *args:None,time()+120)
    assert result['status']=='reviewed' and len(result['observations'])==1 and 'review_history' not in result


@pytest.mark.parametrize('behavior',['blocked_finish','repeated_tool'])
def test_review_rejects_unsupported_finish_and_repeated_lookup(service,monkeypatch,behavior):
    import backend.agents.llm as llm_module
    import backend.tools.regional_task as task_module
    original_fake=llm_module.fake;original_assess=task_module.assess
    def assessment(*args):
        result=original_assess(*args)
        if behavior=='blocked_finish':result['segments'][0].update(value=None,stage=None)
        return result
    def fake(role,payload):
        result=original_fake(role,payload)
        if role=='workflow_statistics':result.update(action='finish' if behavior=='blocked_finish' else 'lookup',tool='trend')
        return result
    monkeypatch.setattr(task_module,'assess',assessment);monkeypatch.setattr(llm_module,'fake',fake)
    service.settings.llm_max_calls=8
    run=run_task(service);stats=service.approval(run.id)['proposal']['workflow']['statistics']
    assert stats['status']=='needs_human'
    assert stats['reason']==('review_retains_blocked_evidence' if behavior=='blocked_finish' else 'statistics_lookup_limit')
    assert len(stats['observations'])==(0 if behavior=='blocked_finish' else 1)


@pytest.mark.parametrize('phase',['initial','final'])
def test_review_deadline_cannot_approve_an_unreviewed_revision(service,monkeypatch,phase):
    import backend.agents.workflow as module
    from backend.tools.regional_task import assess
    from time import time
    assessment=assess(service.settings,task());assessment['segments'][0].update(value=None,stage=None)
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    service.settings.llm_max_calls=8
    plan=module.analyze(service.agents,run.id,'2025-09-01',assessment)
    deadline=time()-1 if phase=='initial' else time()+120;expired=False
    def emit(name,*args):
        nonlocal expired
        if name=='analysis-revised':expired=True
    monkeypatch.setattr(module,'time',lambda:deadline+1 if expired else time())
    result=module.statistical_review(service.agents,service.settings,run.id,'2025-09-01',assessment,plan,emit,deadline)
    assert result['status']=='needs_human' and result['reason']=='deadline'
    assert result.get('revision_check') is None
    assert bool(result['revised_plan'])==(phase=='final')
    calls=[t for t in service.store.traces(run.id,limit=1000) if t['kind']=='llm_call' and t['payload'].get('role')=='workflow_statistics']
    assert len(calls)==(0 if phase=='initial' else 1)
