from copy import deepcopy
import pytest
from backend.tools.regional_resources import policy_gap
from tests.test_graph import service,scenario
from tests.test_regional_task import task


def row(**changes):
    return {'stage':3,'needs':['relationship'],'uncovered_needs':[],'recommendations':[{'id':'one','unknown_conditions':[]}],
            'shortfall':2,'catalog_filter_performed':True,**changes}


def test_slots_do_not_establish_unmet_needs_or_a_field_gap():
    covered=policy_gap(row())
    assert covered['status']=='candidate_coverage' and not covered['research_needed']
    assert covered['recommendation_slot_shortfall']==2 and not covered['absence_established']
    conditional=policy_gap(row(recommendations=[{'id':'one','unknown_conditions':['eligibility:resident']}]))
    assert conditional['status']=='qualification_unconfirmed' and not conditional['research_needed']
    assert conditional['qualification_unconfirmed'] and '자격' in conditional['next_action']
    for changes,status,needed in [({'uncovered_needs':['health']},'unmet_need_hypotheses',True),
            ({'recommendations':[],'uncovered_needs':['relationship'],'shortfall':3},'no_catalog_candidates',True),
            ({'needs':[],'uncovered_needs':[]},'needs_unconfirmed',False),
            ({'stage':None},'insufficient_observation',False),
            ({'reason':'matching_unavailable','catalog_filter_performed':False},'matching_incomplete',False)]:
        result=policy_gap(row(**changes))
        assert result['status']==status and result['research_needed']==needed
        assert result['field_gap_status']=='not_evaluated' and not result['absence_established']
    explicit=policy_gap(row(),True)
    assert explicit['research_needed'] and explicit['research_reasons']==['explicit_request']


@pytest.mark.parametrize('status,complete,candidates,expected',[
    ('tool_error',False,[],'search_failed'),('call_limit',False,[],'search_incomplete'),
    ('completed',False,[],'search_incomplete'),('no_verified_candidates',True,[],'no_verified_candidates_within_scope'),
    ('completed',True,[{'id':'candidate'}],'candidates_found')])
def test_search_results_never_prove_policy_absence(status,complete,candidates,expected):
    result=policy_gap(row(),research={'status':status,'search_complete_within_scope':complete,'candidates':candidates,'search_scope':{'scopes':['central']}})
    assert result['search_status']==expected and result['policy_candidates_returned']==len(candidates)
    assert not result['absence_established'] and result['field_gap_status']=='not_evaluated'
    assert result['search_scope']=={'scopes':['central']}


def test_current_workflow_does_not_search_to_fill_slots_but_honors_explicit_request(service,monkeypatch):
    from backend.tools.catalog import load_catalog
    catalog=load_catalog(service.settings.catalog_path)
    monkeypatch.setattr('backend.graph.load_catalog',lambda _:catalog[:1])
    calls=[]
    monkeypatch.setattr(service.policy_agent,'run',lambda *args:calls.append(args) or {'status':'tool_error','recommendations':[]})
    request=scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json'),research_gaps=True)
    run=service.start(request);proposal=service.approval(run.id)['proposal']
    assert any(a['shortfall']==2 for a in proposal['assignments'])
    assert not calls and 'policy_research' not in proposal
    assert all(a['policy_gap']['status'] in ('qualification_unconfirmed','candidate_coverage') for a in proposal['assignments'])
    requested=request.model_copy(deep=True);requested.payload['policy_research_requested']=True
    run=service.start(requested);proposal=service.approval(run.id)['proposal']
    assert len(calls)==1 and proposal['policy_research']['research_reasons']==['explicit_request']
    assert all(a['policy_gap']['search_status']=='search_failed' for a in proposal['assignments'])
    assert proposal['workflow']['assignments']==proposal['assignments']


def test_no_need_mapping_keeps_three_concepts_without_filler_search(service,monkeypatch):
    from tests.test_policy_alternatives import sets
    monkeypatch.setattr(service.policy_agent,'run',lambda *a:pytest.fail('no confirmed need mapping'))
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *a:pytest.fail('no filler analogue search'))
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task(age_group='prime').model_dump(mode='json'),research_gaps=True))
    proposal=service.approval(run.id)['proposal'];alternatives=sets(service,run.id)
    assert all(a['policy_gap']['status']=='needs_unconfirmed' for a in proposal['assignments'])
    assert alternatives and all(len(s['alternatives'])==3 for s in alternatives)
    for item in [a for s in alternatives for a in s['alternatives']]:
        assert item['claim_limits']['local_need']=='unconfirmed'
        assert item['claim_limits']['effectiveness']=='not_evaluated'


def test_analogue_research_reuses_snapshots_and_separates_as_of(service,monkeypatch):
    from backend.policy.alternatives import research
    run=service.register(scenario());calls=[]
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda name,args:calls.append(args) or {'status':'needs_evidence','analogues':[]})
    context={'gap_contract_version':'policy-gap-1','scope':{'sgg':'11230','as_of':'2026-10-23'},'target_groups':['M/youth'],
        'facts':[],'matching':[{'needs':['relationship'],'uncovered_needs':[],'policy_gap':policy_gap(row())}],'sources':[]}
    assert research(service.policy_designer,run.id,run.id,deepcopy(context))['source_search_status']=='not_requested'
    context['matching'][0]['policy_gap']=policy_gap(row(),True)
    context['sources']=[{'policy_id':'saved'}]
    assert research(service.policy_designer,run.id,run.id,deepcopy(context))['source_search_status']=='existing_snapshot_reused'
    assert not calls
    context['sources']=[];context['matching'][0]['uncovered_needs']=['relationship']
    research(service.policy_designer,run.id,run.id,deepcopy(context));first=len(calls)
    assert first==3
    research(service.policy_designer,run.id,run.id,deepcopy(context));assert len(calls)==first
    context['scope']['as_of']='2026-10-24'
    research(service.policy_designer,run.id,run.id,context);assert len(calls)==2*first
