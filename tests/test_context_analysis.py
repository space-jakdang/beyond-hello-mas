from copy import deepcopy
import pytest
from backend.app.config import Settings
from backend.context.service import ContextService
from backend.context.contracts import ContextRequest,fact_dict
from backend.context.analysis import rates,briefing,context_tool,validate_notes


def profile(tmp_path):
    settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',runtime_storage_root=tmp_path)
    return ContextService(settings).profile(ContextRequest(sgg='11230',dong_cd='11230001',reference_year=2020,as_of='2026-10-24'))


def replace(profile,metric,**changes):
    old=next(f for f in profile['facts'] if f['metric']==metric)
    old.update(changes);old.pop('fact_id')
    old.update(fact_dict(old))


# /ship Step 7 value card
# Value: protects=exact source-bound population and household shares, including absent inputs and invalid ratios;
# fails_when=shares use the wrong denominator or include missing, incompatible or oversized counts;
# why_new=existing assertions checked result counts and bounds without exact arithmetic or absent inputs;
# seam=none; no_claim=generated profiles only; no live statistics or model interpretation acceptance.
def test_rates_preserve_denominators_scope_and_references(tmp_path):
    p=profile(tmp_path);result=rates(p)
    assert len(result)==3 and all(0<=r['value']<=100 and len(r['fact_ids'])==2 for r in result)
    replace(p,'one_person_households',population='different_households')
    assert len(rates(p))==2
    replace(p,'youth_population',sex='M')
    assert len(rates(p))==1
    replace(p,'total_population',value=0.0)
    assert rates(p)==[]
    p=profile(tmp_path)
    for metric,value in (('total_population',1000.0),('senior_population',250.0),
                         ('youth_population',200.0),('total_households',500.0),('one_person_households',100.0)):
        replace(p,metric,value=value)
    households=next(f for f in p['facts'] if f['metric']=='total_households')
    if not any(f['metric']=='general_households' for f in p['facts']):
        p['facts'].append(fact_dict({**{k:v for k,v in households.items() if k!='fact_id'},
                                   'metric':'general_households','value':400.0}))
    else:replace(p,'general_households',value=400.0,population=households['population'])
    expected={'one_person_households_share':25.0,'senior_population_share':25.0,'youth_population_share':20.0}
    assert {r['metric']:r['value'] for r in rates(p)}==expected
    by_metric={f['metric']:f for f in p['facts']}
    assert next(r for r in rates(p) if r['metric']=='one_person_households_share')['fact_ids']==[
        by_metric['one_person_households']['fact_id'],by_metric['general_households']['fact_id']]
    for missing in ('one_person_households','general_households','total_population'):
        changed=deepcopy(p);changed['facts']=[f for f in changed['facts'] if f['metric']!=missing]
        actual={r['metric']:r['value'] for r in rates(changed)}
        if missing=='one_person_households':assert actual=={k:v for k,v in expected.items() if k!='one_person_households_share'}
        elif missing=='general_households':assert actual=={**expected,'one_person_households_share':20.0}
        else:assert actual=={'one_person_households_share':25.0}
    for changes in ({'value':1001.0},{'value':None,'status':'missing','reason':'fixture_missing'},
                    {'reference_year':2015},{'geography_level':'district','geography_code':'11230'},
                    {'source':'kosis'}):
        changed=deepcopy(p);replace(changed,'senior_population',**changes)
        assert {r['metric']:r['value'] for r in rates(changed)}=={
            k:v for k,v in expected.items() if k!='senior_population_share'}
    replace(p,'senior_population',value=0.0)
    assert next(r for r in rates(p) if r['metric']=='senior_population_share')['value']==0.0


# /ship Step 7 value card (pass 2)
# Value: protects=equal isolation facts with distinct observed profiles reach model inputs and preserve supplied review questions;
# fails_when=regional inputs collapse or analyst/statistics question and missing-evidence fields are dropped or replaced;
# why_new=the prior test changed a fact to missing and checked only the generic missing-metric question;
# seam=none; no_claim=scripted model outputs and generated observed profiles; actual model interpretation remains unmeasured.
def test_context_changes_questions_without_inventing_needs(tmp_path):
    p=profile(tmp_path);other=deepcopy(p)
    replace(other,'one_person_households',value=None,status='missing',reason='not_available')
    first=briefing({'11230001':p});second=briefing({'11230001':other})
    assert first['areas'][0]['questions']==[] and second['areas'][0]['questions']==['확인 필요: 1인가구']
    assert len(second['areas'][0]['rates'])==2
    validate_notes([{'fact_ids':[p['facts'][0]['fact_id']]}],{'regional_context':{'11230001':p}})
    with pytest.raises(ValueError):validate_notes([{'fact_ids':['invented']}],{'regional_context':{'11230001':p}})
    with pytest.raises(ValueError):validate_notes([{'fact_ids':[next(f for f in other['facts'] if f['metric']=='one_person_households')['fact_id']]}],{'regional_context':{'11230001':other}})
    from time import time
    from types import SimpleNamespace
    from backend.agents.workflow import AnalystPlan,StatisticsDecision,analyze,statistical_review
    from backend.tools.regional_task import assess
    from backend.tools.indicators import digest
    from tests.test_regional_task import task
    settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',runtime_storage_root=tmp_path)
    assessment=assess(settings,task());selected=next(r['evidence_id'] for r in assessment['segments'] if r['dong_cd']=='11230001')
    captures=[];results=[]
    questions=['1인가구가 적은 구성에서 기존 안내 접점이 적절한지 확인할까요?',
               '1인가구가 많은 구성에서 다양한 연락·연계 접점을 어떻게 확인할까요?']
    for count,question in zip((100.0,400.0),questions):
        observed=profile(tmp_path);replace(observed,'total_households',value=1000.0)
        replace(observed,'one_person_households',value=count)
        assert all(f['status']=='observed' for f in observed['facts'])
        observed['input_hash']=digest({k:v for k,v in observed.items() if k!='input_hash'})
        current={**assessment,'regional_context':{'11230001':observed}}
        identifier=next(f['fact_id'] for f in observed['facts'] if f['metric']=='one_person_households')
        note={'fact_ids':[identifier],'implication':'가구 구성을 반영한 안내 접점 검토',
              'hypothesis':'접점 선호 차이는 현장 확인이 필요한 가설','missing_evidence':[question]}
        supplied=AnalystPlan(summary=question,priority_evidence_ids=[selected])
        replies=[supplied,StatisticsDecision(action='finish',tool='regional_profile',reason='fixture supplied review',
                                            blocked_evidence_ids=[],regional_notes=[note])]
        agents=SimpleNamespace(call=lambda *args:(captures.append({'role':args[-2],'payload':args[-1]}) or replies.pop(0)))
        plan=analyze(agents,'run','sim',current)
        reviewed=statistical_review(agents,settings,'run','sim',current,plan,lambda *args:None,time()+30)
        assert plan['summary']==question and reviewed['status']=='reviewed'
        assert reviewed['regional_notes']==[note]
        assert reviewed['regional_notes'][0]['missing_evidence']==[question]
        assert captures[-1]['payload']['plan']==plan
        assert captures[-2]['payload']['regional_context']['areas'][0]['questions']==[]
        results.append((plan,reviewed))
    assert captures[0]['payload']['facts']==captures[2]['payload']['facts']
    assert [f['stage'] for f in captures[0]['payload']['facts']]==[f['stage'] for f in captures[2]['payload']['facts']]
    views=[captures[i]['payload']['regional_context'] for i in (0,2)]
    inputs=[next(dict(zip(view['fact_columns'],f)) for f in view['areas'][0]['facts']
                 if dict(zip(view['fact_columns'],f))['metric']=='one_person_households') for view in views]
    assert [f['value'] for f in inputs]==[100.0,400.0] and inputs[0]['fact_id']!=inputs[1]['fact_id']
    assert results[0][0]['summary']!=results[1][0]['summary']
    assert results[0][1]['regional_notes'][0]['missing_evidence']!=results[1][1]['regional_notes'][0]['missing_evidence']


# /ship Step 7 value card
# Value: protects=matching-area comparison arithmetic, peer provenance and profile-set hash binding;
# fails_when=peer means/differences or reference IDs drift, or incompatible/missing peers enter a comparison;
# why_new=existing comparison covered only mismatched years and checksum rejection;
# seam=none; no_claim=generated same-definition profiles; no population-risk ranking or provider truth.
def test_context_comparison_requires_matching_source_definitions(tmp_path):
    p=profile(tmp_path);other=deepcopy(p)
    for fact in other['facts']:
        changes={k:v for k,v in fact.items() if k!='fact_id'}
        changes.update(geography_code='11230002',reference_year=2015)
        fact.clear();fact.update(fact_dict(changes))
    assessment={'regional_context':{'11230001':p,'11230002':other}}
    assert context_tool('regional_comparison',assessment)['comparisons']==[]
    broken=deepcopy(p);next(f for f in broken['facts'] if f['metric']=='total_population')['value']+=1
    with pytest.raises(ValueError,match='checksum'):rates(broken)
    replace(p,'total_population',value=1000.0);other=deepcopy(p)
    other['request']['dong_cd']='11230002'
    for fact in other['facts']:
        content={k:v for k,v in fact.items() if k!='fact_id'}
        fact.update(fact_dict({**content,'geography_code':'11230002'}))
    replace(other,'total_population',value=2000.0)
    from backend.tools.indicators import digest
    other['input_hash']=digest({k:v for k,v in other.items() if k!='input_hash'})
    assessment={'regional_context':{'11230001':p,'11230002':other}}
    result=context_tool('regional_comparison',assessment)
    first=next(f for f in p['facts'] if f['metric']=='total_population')['fact_id']
    second=next(f for f in other['facts'] if f['metric']=='total_population')['fact_id']
    assert [c for c in result['comparisons'] if c['fact_id'] in (first,second)]==[
        {'dong_cd':'11230001','fact_id':first,'peer_fact_ids':[second],'peer_count':1,'peer_mean':2000.0,'difference':-1000.0},
        {'dong_cd':'11230002','fact_id':second,'peer_fact_ids':[first],'peer_count':1,'peer_mean':1000.0,'difference':1000.0}]
    assert result['input_hash']==digest({code:report['input_hash'] for code,report in assessment['regional_context'].items()})
    replace(other,'total_population',value=None,status='missing',reason='fixture_missing')
    assert not any(c['fact_id']==first for c in context_tool('regional_comparison',assessment)['comparisons'])
    assert context_tool('regional_comparison',{})['comparisons']==[]
    assert context_tool('regional_profile',{})['areas']==[]


def test_age_specific_households_are_not_all_household_share(tmp_path):
    p=profile(tmp_path);replace(p,'one_person_households',age_definition='65+')
    assert len(rates(p))==2
    replace(p,'population_density',value=10.0)
    next(f for f in p['facts'] if f['metric']=='population_density')['value']=20.0
    with pytest.raises(ValueError,match='checksum'):briefing({'11230001':p})


# /ship Step 7 value card
# Value: protects=selected-area context preserves source definitions, district scope and optional defaults without mutating inputs;
# fails_when=unselected areas leak, priorities discard context or projection drops/promotes/changes source definitions;
# why_new=the original test checked a nonempty single-area payload; pass 2 adds exact metadata/default/district contracts;
# seam=none; no_claim=recorded model inputs and generated profiles; no LLM quality or Supervisor attachment proof.
def test_agent_input_filters_and_empty_revision_keep_context(tmp_path):
    from backend.agents.workflow import context_payload,analyze
    from backend.tools.regional_task import assess
    from tests.test_regional_task import task
    from pydantic import BaseModel
    from types import SimpleNamespace
    settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',runtime_storage_root=tmp_path)
    assessment=assess(settings,task());p=profile(tmp_path)
    assert context_payload(assessment)=={}
    assessment['regional_context']={'11230001':p}
    assert context_payload(assessment,{'priority_evidence_ids':[]})['regional_context']['areas']
    inputs=[]
    class Plan(BaseModel):
        summary:str
        priority_evidence_ids:list[str]
    def call(*args):
        inputs.append(args[-1]);return Plan(summary='지역 집계 문맥을 검토했습니다.',priority_evidence_ids=[])
    assert analyze(SimpleNamespace(call=call),'run','sim',assessment)['summary']
    assert inputs[0]['regional_context']['areas'][0]['facts']
    from backend.tools.regional_statistics import run_tool
    assert run_tool('regional_profile',settings,assessment)['tool']=='regional_profile'
    other=deepcopy(p);other['request']['dong_cd']='11230002'
    assessment['regional_context']['11230002']=other
    selected=next(r['evidence_id'] for r in assessment['segments'] if r['dong_cd']=='11230001')
    assert [a['dong_cd'] for a in context_payload(assessment,{'priority_evidence_ids':[selected]})['regional_context']['areas']]==['11230001']
    assert [a['dong_cd'] for a in context_payload(assessment,{'priority_evidence_ids':[]})['regional_context']['areas']]==['11230001','11230002']
    assert run_tool('regional_profile',settings,assessment)==context_tool('regional_profile',assessment)
    source=deepcopy(p)
    replace(source,'total_population',geography_level='district',geography_code='11230',
            geography_version='fixture-district-v2',source_table='fixture_population_table',
            source_items=['TOTAL'],source_dimensions=['ALL_RESIDENTS'],published_at='2020-12-31T00:00:00Z')
    replace(source,'one_person_households',value=None,status='missing',reason='fixture_source_unavailable')
    replace(source,'total_housing',source_table=None,source_items=[],source_dimensions=[],published_at=None,reason=None)
    defaults={'source_table':None,'source_items':[],'source_dimensions':[],'published_at':None,
              'reason':None,'age_definition':'all_ages','sex':'all'}
    for fact in source['facts']:
        for key,default in defaults.items():
            if fact[key]==default:fact.pop(key)
    from backend.tools.indicators import digest
    source['input_hash']=digest({k:v for k,v in source.items() if k!='input_hash'})
    original=deepcopy(source);current={**assessment,'regional_context':{'11230001':source}}
    analyze(SimpleNamespace(call=call),'run','sim',current)
    raw_area=inputs[-1]['regional_context']['areas'][0]
    area={**raw_area,'facts':[dict(zip(inputs[-1]['regional_context']['fact_columns'],f)) for f in raw_area['facts']]}
    fields=('fact_id','metric','value','unit','reference_year','geography_level','geography_code','geography_version',
            'population','age_definition','sex','source','source_table','source_items','source_dimensions','published_at','status','reason')
    assert tuple(inputs[-1]['regional_context']['fact_columns'])==fields
    assert area['input_hash']==source['input_hash']
    assert area['facts']==[{key:fact.get(key,defaults.get(key)) for key in fields} for fact in source['facts']]
    population=next(f for f in area['facts'] if f['metric']=='total_population')
    assert (population['geography_level'],population['geography_code'],population['geography_version'])==('district','11230','fixture-district-v2')
    assert population['source_table']=='fixture_population_table' and population['source_items']==['TOTAL']
    assert population['source_dimensions']==['ALL_RESIDENTS'] and population['published_at']=='2020-12-31T00:00:00Z'
    housing=next(f for f in area['facts'] if f['metric']=='total_housing')
    assert {key:housing[key] for key in defaults}==defaults
    assert next(f for f in area['facts'] if f['metric']=='one_person_households')['reason']=='fixture_source_unavailable'
    assert run_tool('regional_profile',settings,current)['areas']==[area]
    assert source==original


def test_peer_fact_from_retrieved_tool_is_accepted_only_when_shown(tmp_path):
    p=profile(tmp_path);identifier=p['facts'][0]['fact_id']
    assessment={'regional_context':{'11230001':p}}
    with pytest.raises(ValueError):validate_notes([{'fact_ids':[identifier]}],assessment,{'areas':[]})
    assert validate_notes([{'fact_ids':[identifier]}],assessment,{'areas':[]},[identifier])
    with pytest.raises(ValueError):validate_notes([{'fact_ids':['invented']}],assessment,{'areas':[]},['invented'])


# /ship Step 7 value card
# Value: protects=regional tool names and bounded structured notes preserve the prior no-note decision contract;
# fails_when=regional tools are rejected, note defaults disappear or incomplete/unbounded/extra note fields are accepted;
# why_new=the added model schema had no direct admission or backward-compatibility assertions;
# seam=none; no_claim=Pydantic schema admission only; no model compliance or semantic interpretation quality.
def test_regional_decision_schema_preserves_old_responses_and_bounds_notes():
    from pydantic import ValidationError
    from backend.agents.workflow import StatisticsDecision
    old={'action':'finish','tool':'trend','reason':'fixture','blocked_evidence_ids':[]}
    assert StatisticsDecision.model_validate(old).regional_notes==[]
    note={'fact_ids':['region-fixture'],'implication':'운영 검토','hypothesis':'확인할 가설','missing_evidence':['현장 확인']}
    for tool in ('regional_profile','regional_comparison'):
        assert StatisticsDecision.model_validate({**old,'tool':tool,'regional_notes':[note]}).model_dump()['regional_notes']==[note]
    for malformed in ({**note,'fact_ids':[]},{**note,'missing_evidence':[]},
                      {**note,'fact_ids':['region-fixture']*9},{**note,'implication':'a'*501},
                      {**note,'unsupported':'fixture'}, {k:v for k,v in note.items() if k!='hypothesis'}):
        with pytest.raises(ValidationError):StatisticsDecision.model_validate({**old,'regional_notes':[malformed]})
    with pytest.raises(ValidationError):StatisticsDecision.model_validate({**old,'regional_notes':[note]*6})


# /ship Step 7 value card
# Value: protects=grounded notes, frozen-cache replay and supplied causal-overclaim refusal through one revision/final hold;
# fails_when=unshown notes/stale cache pass, notes disappear or scripted revise/human decisions escape the bounded review;
# why_new=standalone helpers omitted review wiring; pass 2 adds explicit overclaim refusal/revision protocol cases;
# seam=none; no_claim=scripted model decisions and generated profiles; no live provider, model quality or RP06 orchestration proof.
@pytest.mark.parametrize('case',['profile','profile_peer','comparison','cached','bad_cache','no_context',
                                 'unshown_note','missing_note','retained_note','causal_human',
                                 'causal_revise_finish','causal_final_hold','causal_second_revision'])
def test_statistical_review_enforces_regional_evidence_and_replay(tmp_path,monkeypatch,case):
    from time import time
    from types import SimpleNamespace
    from backend.agents.workflow import AnalystPlan,StatisticsDecision,statistical_review
    from backend.tools.regional_task import assess
    from tests.test_regional_task import task
    settings=Settings(_env_file=None,data_mode='sample',llm_mode='fake',runtime_storage_root=tmp_path)
    assessment=assess(settings,task());p=profile(tmp_path);other=deepcopy(p)
    other['request']['dong_cd']='11230002'
    for fact in other['facts']:
        fact.update(fact_dict({**{k:v for k,v in fact.items() if k!='fact_id'},'geography_code':'11230002'}))
    if case=='missing_note':replace(other,'total_population',value=None,status='missing',reason='fixture_missing')
    assessment['regional_context']={'11230001':p,'11230002':other}
    selected=next(r['evidence_id'] for r in assessment['segments'] if r['dong_cd']=='11230001')
    plan={'summary':'fixture','priority_evidence_ids':[selected]}
    identifier=other['facts'][0]['fact_id'] if case in ('profile_peer','comparison','unshown_note','missing_note') else p['facts'][0]['fact_id']
    note={'fact_ids':[identifier],'implication':'운영 검토','hypothesis':'현장 확인 가설','missing_evidence':['서비스 접근 확인']}
    tool='regional_comparison' if case=='comparison' else 'regional_profile'
    decision={'action':'lookup','tool':tool,'reason':'fixture','blocked_evidence_ids':[],'regional_notes':[]}
    if case=='no_context':assessment.pop('regional_context')
    if case in ('unshown_note','missing_note'):decision.update(action='finish',regional_notes=[note])
    if case=='retained_note':decision['regional_notes']=[note]
    decisions=[StatisticsDecision.model_validate(decision),StatisticsDecision.model_validate({**decision,'action':'finish',
        'regional_notes':[] if case=='retained_note' else [note]})]
    if case.startswith('causal_'):
        plan['summary']='1인가구 구성이 고립을 유발하며 개인의 서비스 접근 장벽이 확인되었습니다.'
        reason='지역 집계만으로 고립의 인과 원인이나 개인 접근 장벽을 확정한 해석을 거부합니다.'
        note={**note,'implication':'가구 구성은 기술 통계이며 인과 원인이나 개인 접근 장벽의 관측이 아닙니다.',
              'hypothesis':'서비스 접근 차이는 현장 조사로 확인할 가설입니다.',
              'missing_evidence':['관계망 및 서비스 접근 장벽의 현장 관측']}
        first={**decision,'action':'human' if case=='causal_human' else 'revise','reason':reason,'regional_notes':[note]}
        decisions=[StatisticsDecision.model_validate(first)]
        revised=AnalystPlan(summary='가구 구성의 기술 통계와 서비스 접근 확인 가설을 구별합니다.',priority_evidence_ids=[selected])
        if case!='causal_human':
            final_action={'causal_revise_finish':'finish','causal_final_hold':'human','causal_second_revision':'revise'}[case]
            decisions.extend([revised,StatisticsDecision.model_validate({**first,'action':final_action})])
    inputs=[];roles=[];events=[];cached=[]
    if case in ('cached','bad_cache'):
        cached=[context_tool(tool,assessment)]
        if case=='bad_cache':cached[0]['input_hash']='0'*64
        monkeypatch.setattr('backend.agents.workflow.run_tool',lambda *args:pytest.fail('cached lookup must not execute a tool'))
    agents=SimpleNamespace(call=lambda *args:(roles.append(args[-2]) or inputs.append(args[-1]) or decisions.pop(0)))
    result=statistical_review(agents,settings,'run','sim',assessment,plan,lambda *args:events.append(args),time()+30,cached)
    if case.startswith('causal_'):
        assert inputs[0]['plan']['summary']==plan['summary'] and result['regional_notes']==[note]
        assert result['review_history'][0]['reason']==reason
        assert result['review_history'][0]['regional_notes'][0]['hypothesis']==note['hypothesis']
        assert result['review_history'][0]['regional_notes'][0]['implication']==note['implication']
        assert result['review_history'][0]['regional_notes'][0]['missing_evidence']==note['missing_evidence']
        assert result['observations']==[] and not any(event[0].startswith('statistics-tool') for event in events)
        if case=='causal_human':
            assert result['status']=='needs_human' and result['revised_plan'] is None
            assert roles==['workflow_statistics'] and len(result['review_history'])==1
        else:
            assert roles==['workflow_statistics','workflow_analyst','workflow_statistics']
            assert inputs[1]['feedback']['reason']==reason
            assert inputs[1]['feedback']['statistics']['regional_notes']==[note]
            assert inputs[2]['review_phase']=='final' and inputs[2]['revision_reason']==reason
            assert inputs[2]['plan']==revised.model_dump() and inputs[2]['available_tools']==[]
            assert inputs[2]['remaining_lookups']==0 and result['revised_plan']==revised.model_dump()
            assert [item['phase'] for item in result['review_history']]==['initial','final']
            assert sum(event[0]=='analysis-revised' for event in events)==1
            if case=='causal_revise_finish':
                assert result['status']=='reviewed' and result['revision_check']=='final_statistics_review'
            else:
                assert result['status']=='needs_human' and result.get('revision_check') is None
                if case=='causal_second_revision':assert result['reason']=='final_review_requires_finish_or_human'
        return
    if case in ('bad_cache','no_context','unshown_note','missing_note'):
        assert result['status']=='needs_human' and result['observations']==[]
        assert result['reason']=={'bad_cache':'regional_cached_input_mismatch','no_context':'regional_context_not_available',
                                  'unshown_note':'model_or_tool_unavailable','missing_note':'model_or_tool_unavailable'}[case]
        if case in ('unshown_note','missing_note'):assert result['error_type']=='ValueError'
    else:
        assert result['status']=='reviewed' and result['regional_notes']==[note]
        assert result['observations']==[context_tool(tool,assessment)]
        assert len([event for event in events if event[0]=='statistics-tool-1'])==1
        assert [a['dong_cd'] for a in inputs[0]['regional_context']['areas']]==['11230001']
        assert all(tool in inputs[0]['available_tools'] for tool in ('regional_profile','regional_comparison'))
    if case=='no_context':
        assert 'regional_context' not in inputs[0]
        assert not any(tool.startswith('regional_') for tool in inputs[0]['available_tools'])
