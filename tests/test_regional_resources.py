from copy import deepcopy
from backend.tools.regional_resources import source_ages,source_age_ranges,needs_for,need_profile,candidates
from backend.tools.regional_task import assess
from backend.tools.catalog import load_catalog
from tests.test_regional_task import task
from tests.test_graph import service


def test_source_ages_and_need_mapping_are_evidence_based():
    assert source_ages({'a':['20s','30s'],'b':['19–34']})==(19,39)
    assert source_ages({'a':['65+']})==(65,120)
    assert source_ages({'a':['unknown']}) is None
    assert source_age_ranges({'a':['20s','60s'],'b':['25–34']})==[(20,34),(60,69)]
    assert source_age_ranges({'a':['unknown']}) is None
    row={'index_name':'G','value':.5,'components':{'housing':1,'economic':0,'health':None}}
    assert needs_for(row)==[]
    row['components']={'economic':1};assert needs_for(row)==[]
    row['components']={};assert needs_for(row)==[]


def test_need_profiles_preserve_source_factors_without_inventing_service_needs():
    row={'index_name':'G_chuncheon','value':.5,'components':{'structure':-.3,'visibility_risk':.8,'economic':1,'unknown':2,'health':float('nan'),'housing':float('inf'),'relationship':True}}
    profile=need_profile(row)
    assert profile['needs']==[] and profile['mapping_status']=='unmapped_evidence'
    assert profile['observed_factors']=={'structure':-.3,'visibility_risk':.8,'economic':1,'unknown':2}
    assert profile['invalid_factors']==['health','housing','relationship']
    assert profile['needed_data'] and '현장' in profile['next_action']
    for value in (None,float('nan'),float('inf'),-float('inf')):
        missing=need_profile({**row,'index_name':'S1','value':value})
        assert missing['needs']==[] and missing['mapping_status']=='insufficient_observation'
    youth=need_profile({**row,'index_name':'S1','value':.31,'stage':1,'components':{}})
    assert youth['needs']==['relationship'] and youth['mapping_status']=='index_hypothesis'
    population=need_profile({**row,'index_name':'v3','components':{'youth_population_both_sexes':123}})
    assert population['observed_factors']=={} and population['population_context']=={'youth_population_both_sexes':123}
    assert not population['invalid_factors'] and population['needs']==['relationship']


def test_statistics_holds_and_catalog_time_are_enforced(service):
    a=assess(service.settings,task());resources=load_catalog(service.settings.catalog_path)
    assert all(not r['recommendations'] for r in candidates(a,{'status':'needs_human'},resources))
    stats={'status':'reviewed','blocked_evidence_ids':[a['segments'][0]['evidence_id']]}
    result=candidates(a,stats,resources)
    assert result[0]['reason']=='insufficient_observation' and not result[0]['recommendations']
    old=deepcopy(a);old['task']['as_of']='1900-01-01'
    assert all(not r['recommendations'] for r in candidates(old,{'status':'reviewed'},resources))
    assert all(r['allocation_performed'] is False and r['remaining_capacity'] is None for r in result)


def test_regional_candidate_conditions_reach_saved_evidence_without_a_matching_model(service,monkeypatch):
    from tests.test_workflow_agents import run_task
    resources=[r.model_copy(update={'eligibility_tags':['resident']}) for r in load_catalog(service.settings.catalog_path)]
    monkeypatch.setattr('backend.graph.load_catalog',lambda path:resources)
    run=run_task(service);proposal=service.approval(run.id)['proposal']
    rows=[r for r in proposal['assignments'] if r['recommendations']]
    assert rows
    for row in rows:
        for candidate in row['recommendations']:
            assert candidate['candidate_status']=='conditional'
            assert candidate['condition_checks']['eligibility:resident']=='unknown'
            presented=next(c for c in row['decision_evidence']['presented_candidates'] if c['id']==candidate['id'])
            assert presented['unknown_conditions']==candidate['unknown_conditions']
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM llm_calls WHERE run_id=? AND role='workflow_matching'",(run.id,)).fetchone()[0]==0
    assert proposal['workflow']['matching']['model_calls']==0


def test_legacy_graph_matching_uses_statistics_and_model_is_constrained(service,monkeypatch):
    from tests.test_workflow_agents import run_task
    import backend.agents.llm as module
    import backend.tools.regional_task as task_module
    original_assess=task_module.assess
    def legacy(*args):
        result=original_assess(*args);result['metadata'].pop('matching_mode')
        return result
    monkeypatch.setattr(task_module,'assess',legacy)
    run=run_task(service);p=service.approval(run.id)['proposal']
    assert p['assignments']
    assert all(r['as_of']=='2026-10-21' for r in p['assignments'])
    assert all(r['needs']==['relationship'] for r in p['assignments'])
    assert p['workflow']['matching']['status'] in ('reviewed','needs_human')
    original=module.fake
    def invalid(role,payload):
        response=original(role,payload)
        if role=='workflow_matching':response['selections'][0]['resource_ids']=['invented-resource']
        return response
    monkeypatch.setattr(module,'fake',invalid)
    run=run_task(service);p=service.approval(run.id)['proposal']
    assert not any(r['recommendations'] for r in p['assignments'])


def test_matching_selection_rejects_unknown_and_duplicate_ids(service):
    import pytest
    from backend.agents.workflow_matching import select,MatchingPlan
    a=assess(service.settings,task());stats={'status':'reviewed','reason':'checked','summary':{}}
    rows=candidates(a,stats,load_catalog(service.settings.catalog_path))
    eligible=next(r for r in rows if r['recommendations'])
    eid=eligible['evidence_id'];rid=eligible['recommendations'][0]['id']
    class Agent:
        def __init__(self,selections):self.selections=selections
        def call(self,*args):return MatchingPlan(selections=self.selections,summary='fixture')
    item={'evidence_id':eid,'resource_ids':[rid],'reason':'fixture'}
    selected,meta=select(Agent([item]),'r','t',rows,stats)
    assert meta['status']=='reviewed'
    assert next(r for r in selected if r['evidence_id']==eid)['shortfall']==2
    for invalid in ([{**item,'evidence_id':'unknown'}],[item,item],[{**item,'resource_ids':[rid,rid]}],[{**item,'resource_ids':['invented']}]):
        with pytest.raises(ValueError):select(Agent(invalid),'r','t',rows,stats)
    assert select(Agent([]),'r','t',rows,stats)[1]['status']=='needs_human'


def test_decision_evidence_records_observation_filters_and_actual_choice(service):
    from tests.test_workflow_agents import run_task
    run=run_task(service);proposal=service.approval(run.id)['proposal']
    observations={r['evidence_id']:r for r in proposal['assessment']['segments']}
    for row in proposal['assignments']:
        evidence=row['decision_evidence'];original=observations[row['evidence_id']]
        assert evidence['observation']['value']==original['value']
        assert evidence['observation']['evidence_id']==row['evidence_id']
        assert evidence['provisional_needs']==row['needs']
        presented={c['id'] for c in evidence['presented_candidates']}
        assert {c['id'] for c in row['recommendations']}<=presented
        assert evidence['unknown_conditions']==['individual_eligibility','application_acceptance','remaining_capacity']
        if row['recommendations']:assert evidence['selection_reason'] and evidence['model_reason'] is None
        assert [c['id'] for c in evidence['presented_candidates']]==[c['id'] for c in row['recommendations']]
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM llm_calls WHERE run_id=? AND role='workflow_matching'",(run.id,)).fetchone()[0]==0
    assert proposal['workflow']['matching']['matching_mode']=='deterministic-regional-1'


def test_statistical_profiles_reach_matching_without_changing_verified_filters(service,monkeypatch):
    from tests.test_workflow_agents import run_task
    seen=[];original=service.agents.call
    def capture(run_id,sim_ts,role,payload):
        if role=='workflow_matching':
            seen.append(payload)
        return original(run_id,sim_ts,role,payload)
    monkeypatch.setattr(service.agents,'call',capture)
    run=run_task(service);p=service.approval(run.id)['proposal']
    assert not seen and p['workflow']['matching']['status']=='reviewed'
    profiles={r['evidence_id']:r for r in p['workflow']['statistics']['summary']['policy_needs']['profiles']}
    assert all({k:v for k,v in r['decision_evidence']['statistical_context'].items() if k!='insight'}==profiles[r['evidence_id']] for r in p['assignments'])


def test_deterministic_matching_keeps_empty_and_unreviewed_results_held(service):
    from backend.tools.regional_resources import select_candidates
    assessment=assess(service.settings,task())
    for status in ('reviewed','needs_human'):
        rows,metadata=select_candidates(candidates(assessment,{'status':status},[]))
        assert metadata['status']=='needs_human' and metadata['model_calls']==0
        assert all(not row['recommendations'] and row['decision_evidence']['model_reason'] is None for row in rows)
        if status=='needs_human':assert all('계산하지 않았습니다' in row['decision_evidence']['selection_reason'] for row in rows)
    assert select_candidates([])[1]['status']=='needs_human'


def test_deterministic_selector_failure_preserves_mode_and_holds_candidates(service,monkeypatch):
    from tests.test_workflow_agents import run_task
    monkeypatch.setattr('backend.tools.regional_resources.select_candidates',lambda *args:(_ for _ in ()).throw(ValueError('selector failed')))
    run=run_task(service);proposal=service.approval(run.id)['proposal']
    matching=proposal['workflow']['matching']
    assert matching['status']=='needs_human' and matching['model_calls']==0
    assert matching['matching_mode']=='deterministic-regional-1'
    assert proposal['assignments'] and all(not r['recommendations'] for r in proposal['assignments'])
    assert all(r['matching_mode']==r['decision_evidence']['matching_mode']=='deterministic-regional-1' for r in proposal['assignments'])
    with service.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM llm_calls WHERE run_id=? AND role='workflow_matching'",(run.id,)).fetchone()[0]==0
