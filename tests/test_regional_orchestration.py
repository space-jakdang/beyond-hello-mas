import json
from copy import deepcopy
from uuid import uuid4
import pytest
from tests.test_graph import service,scenario
from tests.test_regional_task import task
from backend.regional_batch import BatchRequest,create,execute


def test_versioned_single_freezes_context_and_reuses_available_resources(service,monkeypatch):
    service.settings.llm_max_calls=10
    selected=task(dong_cd='11230001')
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',policy_context_version='regional-policy-2',task=selected.model_dump(mode='json')))
    p=service.approval(run.id)['proposal']
    assert p['assessment']['regional_context']
    with service.store.connection() as db:
        stored=json.loads(db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=?',(run.id,)).fetchone()[0])
    assert stored['proposal_version']=='regional-policy-2' and len(stored['alternatives']) in (0,3)
    assert stored['scope']['target_groups']==['M/youth']
    assert stored['response_decisions']
    from backend.context.orchestration import freeze
    monkeypatch.setattr('backend.context.service.ContextService.profile',lambda *args: (_ for _ in ()).throw(AssertionError('must not refetch')))
    assert freeze(service,run.id,p['task'],[])==p['assessment']['regional_context']


def test_batch_context_is_shared_and_one_set_is_owned_by_parent(service):
    service.settings.llm_max_calls=10
    body=create(service,BatchRequest(request_id=uuid4(),task=task(dong_cd='11230001').model_dump(mode='json'),sex='all',age_group='youth',policy_context_version='regional-policy-2'))
    with service.store.connection() as db:
        assessments=[json.loads(r[0]) for r in db.execute('SELECT assessment FROM regional_batch_children WHERE batch_id=?',(body['id'],))]
    assert len(assessments)==2 and all(a['regional_context']==body['regional_context'] for a in assessments)
    execute(service,body['id'])
    with service.store.connection() as db:
        sets=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_alternative_sets')]
    assert len(sets)==1 and sets[0]['owner_id']==body['id']
    assert set(sets[0]['scope']['target_groups'])=={'M/youth','F/youth'}


def test_cancel_during_design_does_not_publish_a_set(service,tmp_path,monkeypatch):
    from backend.policy.pinpoint import generate
    from tests.test_pinpoint_policy import context
    import backend.agents.llm as llm
    body=create(service,BatchRequest(request_id=uuid4(),task=task(dong_cd='11230001').model_dump(mode='json'),sex='M',age_group='youth',policy_context_version='regional-policy-2'))
    run=service.register(scenario('monthly'));c=context(tmp_path);scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    original=llm.fake
    def cancel(role,payload):
        result=original(role,payload)
        with service.store.connection(write=True) as db:
            current=json.loads(db.execute('SELECT body FROM regional_batches WHERE id=?',(body['id'],)).fetchone()[0]);current['cancelled']=True
            db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(current),body['id']))
        return result
    monkeypatch.setattr(llm,'fake',cancel)
    assert generate(service.policy_designer,body['id'],run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})==[]
    with service.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM policy_alternative_sets').fetchone()[0]==0


# /ship Step 7 pass 2 extension
# Value: protects=two verified groups produce three parent drafts within the native input cap with all source definitions intact;
# fails_when=duplicate metadata overflows 24000 bytes, a definition column disappears, or model compaction changes frozen evidence;
# why_new=the positive case checked draft counts but not actual model packets or their complete source metadata;
# seam=none; no_claim=fake-mode protocol and byte contracts, not actual model quality or policy effectiveness.
def test_partial_age_coverage_creates_one_parent_set_for_two_groups(service,monkeypatch):
    import backend.regional_batch as batches
    import backend.agents.llm as llm
    original=batches.load_catalog
    monkeypatch.setattr(batches,'load_catalog',lambda path:[r.model_copy(update={'age_min':20,'age_max':29}) for r in original(path)])
    original_fake=llm.fake;packets=[]
    def capture(role,payload):
        if role=='policy_alternatives':packets.append(deepcopy(payload))
        return original_fake(role,payload)
    monkeypatch.setattr(llm,'fake',capture)
    assert service.settings.llm_max_input_bytes==24000
    service.settings.llm_max_calls=10
    body=create(service,BatchRequest(request_id=uuid4(),task=task(dong_cd='11230001').model_dump(mode='json'),sex='all',age_group='youth',policy_context_version='regional-policy-2'))
    frozen=deepcopy(body['regional_context'])
    execute(service,body['id'])
    with service.store.connection() as db:
        sets=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_alternative_sets')]
    assert len(sets)==1 and sets[0]['owner_id']==body['id']
    assert len(sets[0]['alternatives'])==3,sets[0].get('fallback_reason')
    assert {r['target_group'] for r in sets[0]['response_decisions']}=={'M/youth','F/youth'}
    assert all(a['target_groups']==['F/youth','M/youth'] for a in sets[0]['alternatives'])
    assert len(packets)==1 and service.settings.llm_max_input_bytes==24000
    packet={'prompt':(llm.PROMPTS/'policy_alternatives.txt').read_text(),'payload':packets[0],
            'schema':llm.schema_for('policy_alternatives',packets[0]).model_json_schema()}
    assert len(json.dumps(packet,ensure_ascii=False).encode())<=24000
    columns=packets[0]['regional_profile']['fact_columns']
    assert columns==['fact_id','metric','value','unit','reference_year','geography_level','geography_code',
        'geography_version','population','age_definition','sex','source','source_table','source_items',
        'source_dimensions','published_at','status','reason']
    for area in packets[0]['regional_profile']['areas']:
        raw=frozen[area['dong_cd']]['facts']
        assert len(area['facts'])==len(raw)
        for values,source in zip(area['facts'],raw):
            shown=dict(zip(columns,values))
            assert len(values)==18 and shown['fact_id'].startswith('R')
            assert {k:shown[k] for k in columns[1:]}=={k:source[k] for k in columns[1:]}
    assert body['regional_context']==frozen and sets[0]['evidence']['regional_profile']==frozen['11230001']
    with service.store.connection() as db:
        assert json.loads(db.execute('SELECT body FROM regional_context_snapshots WHERE owner_id=?',(body['id'],)).fetchone()[0])==frozen


def test_complementary_resources_do_not_fabricate_an_age_gap():
    from backend.context.orchestration import age_coverage_gaps
    row={'age_group':'youth','source_age_ranges':[[20,29],[30,39]],'recommendations':[{'needs':['relationship'],'eligible_age_ranges':[[20,29]]},{'needs':['relationship'],'eligible_age_ranges':[[30,39]]}]}
    assert age_coverage_gaps(row,'relationship')==[]
    row['recommendations'].pop()
    assert '30–39세' in age_coverage_gaps(row,'relationship')[0]


def test_age_gap_intervals_do_not_include_covered_ages():
    from backend.context.orchestration import age_coverage_gaps
    row={'age_group':'youth','source_age_ranges':[[20,29]],'recommendations':[{'needs':['relationship'],'eligible_age_ranges':[[20,24]]},{'needs':['relationship'],'eligible_age_ranges':[[28,29]]}]}
    assert '25–27세' in age_coverage_gaps(row,'relationship')[0]
    assert '25–29세' not in age_coverage_gaps(row,'relationship')[0]
    row['recommendations'][0].pop('eligible_age_ranges')
    assert age_coverage_gaps(row,'relationship')==[]


# /ship Step 7 pass 1 extension
# Value: protects=only visible or source-bound reread text can support policy reviews;
# fails_when=hidden suffixes or fields from missing/changed details authorize guidance;
# why_new=the earlier field test checked visibility only, without citation or revocation oracles;
# seam=none; no_claim=synthetic official-condition fixtures, not real provider acceptance or policy suitability.
def test_complete_policy_field_is_visible_and_external_sources_cannot_be_injected(service,tmp_path):
    import pytest
    from backend.policy.agent import PolicyTask,PolicyDecision
    from backend.tools.indicators import digest
    task_input=PolicyTask(goal='검토',research_version='regional-research-1')
    text='앞부분 '*200+'마지막 대상 조건'
    observation={'action':{'action':'policy_detail'},'arguments':{'policy_id':'P1'},'result':{'status':'live','policy':{'id':'P1','title':'테스트 정책','scope':'central','support':text,'eligibility':'주민'}}}
    request=PolicyDecision(action='policy_field',query='',page=1,policy_id='P1',detail_field='support',recommendations=[],reason='원문 뒷부분 확인')
    assert service.policy_agent.arguments(request,[observation],task_input)=={'policy_id':'P1','field':'support'}
    field={'action':request.model_dump(),'arguments':{'policy_id':'P1','field':'support'},'result':{'policy_id':'P1','field':'support','value':text,'frozen':True,'source_hash':digest(observation['result']['policy']),'status':'available'}}
    view=service.policy_agent.model_payload(task_input,[observation,field],1)
    assert view['observations'][-1]['result']['value'].endswith('마지막 대상 조건')
    with pytest.raises(ValueError,match='regional research'):service.register(scenario('policy',goal='정책 검토',research_version='regional-research-1',existing_resources=[{'id':'fabricated'}]))
    from tests.test_regional_research import inputs
    from backend.policy.research_contracts import NeedReview,validate_reviews,visible_policy_fields
    checked_task,result,row=inputs(tmp_path/'field-review')
    checked_task.scopes=['central']
    observation['result']['conditions']=result['recommendations'][0]['conditions']
    row['citations']=[{'policy_id':'P1','field':'support','quote':'마지막 대상 조건'}]
    original=deepcopy((observation,field))
    excerpt=service.policy_agent.model_payload(checked_task,[observation],1)
    with pytest.raises(ValueError,match='outside model view'):
        validate_reviews([NeedReview(**row)],checked_task,result,[observation],visible_policy_fields(excerpt))
    reread=service.policy_agent.model_payload(checked_task,[observation,field],1)
    verified=validate_reviews([NeedReview(**row)],checked_task,result,[observation],visible_policy_fields(reread))[0]
    assert verified['decision']=='reuse_existing' and verified['guidance'][0]['support']==text
    assert (observation,field)==original
    run=service.register(scenario('policy',goal='내부 고정 원문 검증'))
    with service.store.connection(write=True) as db:
        db.execute('INSERT INTO policy_steps VALUES (?,?,?)',(run.id,0,json.dumps(observation)))
    worker_calls=[]
    def decide(*args):
        worker_calls.append(args[-2])
        if not any(o['action']['action']=='policy_field' for o in args[-1]['observations']):return request
        return PolicyDecision(action='finish',query='',page=1,policy_id=None,recommendations=[],
            need_reviews=[NeedReview(**row)],reason='고정 원문을 확인한 검토')
    service.agents.call=decide
    service.policy_agent.call_tool=lambda *args:pytest.fail('a frozen field read must not call a provider')
    finished=service.policy_agent.run(run.id,'2026-10-24T09:00:00+09:00',checked_task)
    assert finished['status']=='completed' and finished['need_reviews'][0]['guidance'][0]['support']==text
    assert worker_calls==['policy_decision','policy_decision']
    with service.store.connection() as db:
        saved=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_steps WHERE run_id=? ORDER BY step',(run.id,))]
    assert [o['action']['action'] for o in saved]==['policy_detail','policy_field']
    assert saved[-1]['result']=={'policy_id':'P1','field':'support','value':text,'frozen':True,
        'source_hash':digest(observation['result']['policy']),'status':'available'}
    assert (observation,field)==original
    missing={'action':{'action':'policy_detail'},'arguments':{'policy_id':'P1'},'result':{'status':'not_found','policy':None}}
    with pytest.raises(ValueError,match='unobserved_policy_field'):
        service.policy_agent.arguments(request,[observation,field,missing],checked_task)
    revoked=service.policy_agent.model_payload(checked_task,[observation,field,missing],1)
    assert revoked['observations'][1]['result']['status']=='superseded'
    assert revoked['observations'][1]['result']['value'] is None
    assert 'P1' not in visible_policy_fields(revoked)
    changed=deepcopy(observation);changed['result']['policy']['support']='새 버전의 공식 지원 내용'
    current=service.policy_agent.model_payload(checked_task,[observation,field,changed],1)
    assert current['observations'][1]['result']['status']=='superseded'
    assert current['observations'][1]['result']['value'] is None
    assert visible_policy_fields(current)['P1']['support']=='새 버전의 공식 지원 내용'


def test_display_concept_does_not_truncate_observed_source_ages():
    from backend.context.orchestration import age_coverage_gaps
    row={'age_group':'youth','source_age_ranges':[[20,39]],'recommendations':[{'needs':['relationship'],'eligible_age_ranges':[[20,34]]}]}
    assert '35–39세' in age_coverage_gaps(row,'relationship')[0]
    row['recommendations'][0]['eligible_age_ranges']=[[20,39]]
    assert age_coverage_gaps(row,'relationship')==[]


# /ship Step 7 pass 1
# Value: protects=v4 source ages and shared profiles survive single and parent-only held batch results;
# fails_when=workflow meaning changes, children generate sets, or ordinal signals invent service needs;
# why_new=prior v4 tests expanded cohorts but never executed the policy-context graph and parent store;
# seam=none; no_claim=sample profiles and generated v4 rows, not measured needs or actual model quality.
def test_v4_policy_context_keeps_source_contract_and_parent_only_evidence_holds(service,monkeypatch):
    from backend.context.service import ContextService
    from backend.regional_batch import public,read
    from tests.v4_support import group_data
    data=group_data();profile_calls=[];original=ContextService.profile
    monkeypatch.setattr('backend.tools.neighborhoods.group_analysis_v4',lambda settings,week:deepcopy(data))
    def profile(source,request):
        profile_calls.append(request.dong_cd)
        return original(source,request)
    monkeypatch.setattr(ContextService,'profile',profile)
    service.settings.llm_max_calls=10
    selected={'sgg':'11230','sex':'M','source_age_band':'20대','dong_cd':'11230001',
              'as_of':'2026-10-25','card_week':'2025-12-15'}
    run=service.start(scenario('monthly',workflow_version='regional-workflow-2',
        policy_context_version='regional-policy-2',task=selected))
    proposal=service.approval(run.id)['proposal']
    assert proposal['workflow_version']=='regional-workflow-2'
    assert proposal['assessment']['metadata']['statistics_version']=='3'
    assert proposal['task']['source_age_band']=='20대' and proposal['task']['card_week']=='2025-12-15'
    assert proposal['policy_research']['research_version']=='regional-research-2'
    assert proposal['policy_research']['need_reviews'][0]['reason']=='need_not_established'
    assert proposal['policy_alternatives']['actual_counts']=={'11230001':0}
    assert 'alternatives_per_dong' not in proposal['policy_alternatives']
    request=BatchRequest(request_id=uuid4(),workflow_version='regional-workflow-2',
        policy_context_version='regional-policy-2',task={k:v for k,v in selected.items() if k not in ('sex','source_age_band')})
    body=create(service,request)
    assert len(body['children'])==12 and create(service,request)==body
    assert profile_calls==['11230001','11230001']
    with service.store.connection() as db:
        assessments=[json.loads(row[0]) for row in db.execute('SELECT assessment FROM regional_batch_children WHERE batch_id=?',(body['id'],))]
    assert len(assessments)==12 and all(a['regional_context']==body['regional_context'] for a in assessments)
    execute(service,body['id'])
    assert all(service.store.get_run(child['run_id']).status=='awaiting_approval' for child in body['children'])
    with service.store.connection() as db:
        sets=[json.loads(row[0]) for row in db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=?',(body['id'],))]
        child_owners=[row[0] for row in db.execute('SELECT DISTINCT owner_id FROM policy_alternative_sets')]
        snapshots=db.execute('SELECT COUNT(*) FROM regional_context_snapshots').fetchone()[0]
        design_calls=db.execute("SELECT COUNT(*) FROM llm_calls WHERE role='policy_alternatives'").fetchone()[0]
    assert len(sets)==1 and sets[0]['alternatives']==[] and sets[0]['status']=='needs_evidence'
    assert sets[0]['missing_groups']==[] and len(sets[0]['response_decisions'])==12
    assert all(r['need']=='unconfirmed' and r['reason']=='need_not_established' for r in sets[0]['response_decisions'])
    expected_ages={'20대':[[20,29]],'30대':[[30,39]],'40대':[[40,49]],
                   '50대':[[50,59]],'60대':[[60,69]],'70대+':[[70,120]]}
    for review in sets[0]['response_decisions']:
        age=review['target_group'].split('/')[1]
        assert review['source_bands']=={'dong_stage_age':[age]} and review['source_age_ranges']==expected_ages[age]
    assert all(f['value'] is None and f['card_week']=='2025-12-15' for f in sets[0]['evidence']['facts'])
    assert set(sets[0]['scope']['target_groups'])=={child['sex']+'/'+child['source_age_band'] for child in body['children']}
    assert not {child['run_id'] for child in body['children']}&set(child_owners)
    assert snapshots==2 and design_calls==0 and profile_calls==['11230001','11230001']
    status=public(service,read(service,body['id']))
    assert status['status']=='completed_with_evidence_hold' and status['policy_proposals']['evidence_hold_count']==1
    assert status['policy_proposals']['actual_counts']=={'11230001':0}


# /ship Step 7 pass 1
# Value: protects=owner snapshots remain immutable across new source years and reject retargeting;
# fails_when=replay fetches new data or another date, jurisdiction, dong set or mode replaces the snapshot;
# why_new=the earlier reuse test did not change configuration or challenge any frozen owner scope;
# seam=none; no_claim=owned SQLite and sample profiles, not provider cache or cross-process race acceptance.
def test_owner_snapshot_replay_keeps_old_year_and_rejects_scope_changes(service,monkeypatch):
    from backend.context.orchestration import freeze
    from backend.regional_batch import BatchConflict
    selected=task(dong_cd='11230001').model_dump(mode='json')
    dongs=[{'dong_cd':'11230001','dong_nm':'생성 동'}];owner=str(uuid4())
    service.settings.regional_reference_year=2020
    first=freeze(service,owner,selected,dongs)
    assert first['11230001']['request']['reference_year']==2020
    monkeypatch.setattr('backend.context.service.ContextService.profile',lambda *args:pytest.fail('frozen owner must not collect again'))
    service.settings.regional_reference_year=2025
    assert freeze(service,owner,selected,dongs)==first
    for changed,different_dongs in (({**selected,'as_of':'2026-10-23'},dongs),
                                  ({**selected,'sgg':'32010'},dongs),
                                  (selected,[{'dong_cd':'11230002','dong_nm':'다른 동'}])):
        with pytest.raises(BatchConflict,match='scope'):
            freeze(service,owner,changed,different_dongs)
    monkeypatch.setattr(service.settings,'data_mode','local')
    with pytest.raises(BatchConflict,match='data mode'):freeze(service,owner,selected,dongs)
    with service.store.connection() as db:
        rows=db.execute('SELECT body FROM regional_context_snapshots WHERE owner_id=?',(owner,)).fetchall()
    assert len(rows)==1 and json.loads(rows[0][0])==first


# /ship Step 7 pass 1
# Value: protects=policy coverage follows actual and disjoint source ages, with legacy concept compatibility;
# fails_when=display ages narrow observations, gap ages match a policy, or inconsistent source definitions pass;
# why_new=prior age-gap tests checked interval arithmetic but not the government's material target boundary;
# seam=none; no_claim=official-condition-shaped fixtures, not individual eligibility or live API acceptance.
def test_research_v2_checks_actual_disjoint_age_ranges_and_legacy_fallback(tmp_path):
    from backend.policy.research_contracts import target_checks,MaterialPolicyError,ResearchNeed
    from pydantic import ValidationError
    from tests.test_regional_research import inputs
    delegated,result,_=inputs(tmp_path)
    delegated.research_version='regional-research-2'
    need=delegated.needs[0]
    need.source_bands={'measured':['20s','30s']};need.source_age_ranges=[(20,39)]
    candidate=result['recommendations'][0]
    candidate['conditions'].update(JA0110=19,JA0111=34)
    checked=target_checks(candidate,need,delegated)
    assert checked['age_coverage']=='partial' and checked['eligible_age_ranges']==[[20,34]]
    candidate['conditions'].update(JA0110=20,JA0111=39)
    assert target_checks(candidate,need,delegated)['age_coverage']=='full'
    need.source_bands={'measured':['20s','40s']};need.source_age_ranges=[(20,29),(40,49)]
    candidate['conditions'].update(JA0110=30,JA0111=39)
    with pytest.raises(MaterialPolicyError,match='policy_target_mismatch'):target_checks(candidate,need,delegated)
    candidate['conditions'].update(JA0110=20,JA0111=49)
    checked=target_checks(candidate,need,delegated)
    assert checked['age_coverage']=='full' and checked['eligible_age_ranges']==[[20,29],[40,49]]
    need.source_age_ranges=[(19,34)]
    with pytest.raises(MaterialPolicyError,match='source_age_definition_unavailable'):target_checks(candidate,need,delegated)
    need.source_bands={};need.source_age_ranges=[]
    with pytest.raises(MaterialPolicyError,match='source_age_definition_unavailable'):target_checks(candidate,need,delegated)
    delegated.research_version='regional-research-1';candidate['conditions'].update(JA0110=19,JA0111=34)
    assert target_checks(candidate,need,delegated)['age_coverage']=='full'
    with pytest.raises(ValidationError):ResearchNeed.model_validate({**need.model_dump(),'source_age_ranges':[[True,29]]})


# /ship Step 7 pass 1
# Value: protects=expired work and mismatched frozen scopes cannot persist unchecked policy drafts;
# fails_when=late model output is admitted, a new call starts past deadline, or foreign scope is saved;
# why_new=existing cancellation and replay cases did not exercise deadline or first-save week/profile bounds;
# seam=none; no_claim=scripted model decisions and clocks; in-flight provider cancellation is not established.
@pytest.mark.parametrize('case',['design_before','design_after','policy_before','policy_after','policy_tool','week_scope','profile_scope'])
def test_deadlines_and_frozen_scope_never_publish_unchecked_drafts(service,tmp_path,monkeypatch,case):
    from types import SimpleNamespace
    from backend.policy.pinpoint import generate,fixture_design
    from backend.policy.alternative_contracts import PinpointDecision
    from backend.policy.agent import PolicyDecision
    from tests.test_pinpoint_policy import context
    from tests.test_regional_research import inputs
    run=service.register(scenario('monthly'));calls=[]
    c=context(tmp_path/'design');scope={**c['scope'],'policy_context_version':'regional-policy-2','selected_week':'2025-12-15'}
    c['scope']=deepcopy(scope);dong={k:c[k] for k in ('dong_cd','dong_nm')}
    if case.endswith('_scope'):
        if case=='week_scope':c['scope']['selected_week']='2025-12-08'
        else:c['regional_profile']['request']['dong_cd']='11230002'
        monkeypatch.setattr(service.agents,'call',lambda *args:pytest.fail('invalid scope must stop before a model'))
        with pytest.raises(ValueError,match='frozen_.*scope_mismatch'):
            generate(service.policy_designer,run.id,run.id,scope,[dong],[],contexts={c['dong_cd']:c})
        with service.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM policy_alternative_sets WHERE owner_id=?',(run.id,)).fetchone()[0]==0
        return
    if case.startswith('design_'):
        clock=[2. if case=='design_before' else 0.]
        monkeypatch.setattr('backend.policy.pinpoint.time',SimpleNamespace(time=lambda:clock[0]))
        def late_design(*args):
            calls.append(args[-2]);clock[0]=2.
            return PinpointDecision(action='draft',information_requests=[],**fixture_design(args[-1]))
        monkeypatch.setattr(service.agents,'call',late_design)
        body=generate(service.policy_designer,run.id,run.id,scope,[dong],[],contexts={c['dong_cd']:c},deadline=1.)[0]
        assert body['status']=='needs_evidence' and body['fallback_reason']=='deadline' and body['alternatives']==[]
        assert calls==([] if case=='design_before' else ['policy_alternatives'])
        assert generate(service.policy_designer,run.id,run.id,scope,[dong],[],contexts={c['dong_cd']:c})[0]==body
        with service.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM policy_alternative_sets WHERE owner_id=?',(run.id,)).fetchone()[0]==1
        return
    delegated,_,_=inputs(tmp_path/'research')
    moments=iter([2.] if case=='policy_before' else [0.,2.] if case=='policy_after' else [0.,0.,2.])
    monkeypatch.setattr('backend.policy.agent.time',SimpleNamespace(time=lambda:next(moments)))
    def late_policy(*args):
        calls.append(args[-2])
        return PolicyDecision(action='policy_refresh',query='',page=1,policy_id=None,recommendations=[],reason='scripted deadline')
    monkeypatch.setattr(service.agents,'call',late_policy)
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:pytest.fail('expired worker must not begin a tool'))
    result=service.policy_agent.run(run.id,'2026-10-24T09:00:00+09:00',delegated,deadline=1.)
    assert result['status']=='deadline' and result['recommendations']==[]
    assert result['need_reviews'][0]['decision']=='needs_evidence' and result['need_reviews'][0]['reason']=='deadline'
    assert calls==([] if case=='policy_before' else ['policy_decision'])
    with service.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM policy_steps WHERE run_id=?',(run.id,)).fetchone()[0]==0


# /ship Step 7 pass 2
# Value: protects=children share the first owner policy detail across single and batch tools while separate owners obtain their own version;
# fails_when=tool shape splits the detail cache, replay refetches, or later children replace the first frozen text or conditions;
# why_new=existing worker tests use one run and never alternate detail tool shapes under a shared parent;
# seam=none; no_claim=scripted Gov24 responses and decisions, not live provider snapshots or concurrent fetch serialization.
@pytest.mark.parametrize('first_tool',['policy_detail','policy_details'])
def test_owner_research_reuses_canonical_details_across_children_and_replay(service,monkeypatch,first_tool):
    from backend.policy.agent import PolicyTask,PolicyDecision
    batch=create(service,BatchRequest(request_id=uuid4(),task=task(dong_cd='11230001').model_dump(mode='json'),sex='all',age_group='youth'))
    children=[c['run_id'] for c in batch['children']]
    standalone=service.register(scenario('policy',goal='별도 소유자 조사'))
    delegated=PolicyTask(goal='고정 정책 검토',scopes=['gangnam'],research_version='regional-research-2')
    tools={children[0]:first_tool,children[1]:'policy_details' if first_tool=='policy_detail' else 'policy_detail',standalone.id:'policy_detail'}
    version=[1];calls=[];captured={}
    def detail(pid):
        return {'status':'live','policy':{'id':pid,'title':pid+' 공식 사업','scope':'gangnam',
            'support':'고정 지원 원문 '+str(version[0]),'eligibility':'지역 주민'},
            'conditions':{'서비스ID':pid,'JA0110':20,'JA0111':29+version[0],'JA0101':'Y','JA0102':'Y'}}
    def tool(name,args):
        calls.append((name,deepcopy(args)))
        if name=='policy_search':return {'status':'live','items':[detail(pid)['policy'] for pid in ('P1','P2')],'total':2,'next_page':None}
        if name=='policy_detail':return detail(args['policy_id'])
        assert name=='policy_details'
        return {'status':'complete','items':[detail(pid) for pid in args['policy_ids']]}
    def decide(run_id,sim_ts,role,payload):
        observations=payload['observations'];action='policy_search' if not observations else tools[run_id] if len(observations)==1 else 'finish'
        recommendations=[]
        if action=='finish':
            result=observations[-1]['result'];rows=result.get('items',[result])
            policy=next(r['policy'] for r in rows if r['policy']['id']=='P1')
            recommendations=[{'policy_id':'P1','field':'support','value':policy['support'],'explanation':'고정 원문 인용'}]
        return PolicyDecision(action=action,query='고립',page=1,policy_id='P1' if action=='policy_detail' else None,
            policy_ids=['P1','P2'] if action=='policy_details' else [],recommendations=recommendations,reason='scripted owner snapshot')
    monkeypatch.setattr(service.policy_agent,'call_tool',tool)
    monkeypatch.setattr(service.agents,'call',decide)
    first=service.policy_agent.run(children[0],'2026-10-24T09:00:00+09:00',delegated)
    assert first['status']=='completed' and first['recommendations'][0]['policy']['support']=='고정 지원 원문 1'
    version[0]=2
    second=service.policy_agent.run(children[1],'2026-10-24T09:00:00+09:00',delegated)
    assert second['status']=='completed' and second['recommendations'][0]==first['recommendations'][0]
    expected=[('policy_search',{'scopes':['gangnam'],'query':'고립','page':1,'per_page':5})]
    expected.append((first_tool,{'policy_id':'P1'} if first_tool=='policy_detail' else {'policy_ids':['P1','P2']}))
    if first_tool=='policy_detail':expected.append(('policy_details',{'policy_ids':['P2']}))
    assert calls==expected
    with service.store.connection() as db:
        for run_id in children:
            captured[run_id]=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_steps WHERE run_id=? ORDER BY step',(run_id,))]
        cache=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_alternative_research WHERE owner_id=?',(batch['id'],))]
    assert len(cache)==3
    for observations in captured.values():
        result=observations[-1]['result'];rows=result.get('items',[result])
        frozen=next(r for r in rows if r['policy']['id']=='P1')
        assert frozen['policy']['support']=='고정 지원 원문 1' and frozen['conditions']['JA0111']==30
    before=deepcopy(calls)
    assert service.policy_agent.run(children[0],'2026-10-24T09:00:00+09:00',delegated)==first
    assert service.policy_agent.run(children[1],'2026-10-24T09:00:00+09:00',delegated)==second
    assert calls==before
    separate=service.policy_agent.run(standalone.id,'2026-10-24T09:00:00+09:00',delegated)
    assert separate['recommendations'][0]['policy']['support']=='고정 지원 원문 2'
    assert separate['recommendations'][0]['conditions']['JA0111']==31 and len(calls)==len(before)+2
    with service.store.connection() as db:
        assert {run_id:[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_steps WHERE run_id=? ORDER BY step',(run_id,))] for run_id in children}==captured


# /ship Step 7 pass 2
# Value: protects=conflicting frozen policy text or conditions produce one durable parent evidence hold with both raw versions retained;
# fails_when=last-child sources silently win, conflicting guidance survives, or generation or research begins despite the conflict;
# why_new=the existing snapshot conflict test checked regional hashes and duplicate reviews, not conflicting policy IDs across cohorts;
# seam=none; no_claim=synthetic legacy child proposals, not live source correctness or full batch failure recovery.
@pytest.mark.parametrize('conflict',['support','conditions'])
def test_conflicting_child_policy_versions_persist_parent_hold_without_calls(service,tmp_path,monkeypatch,conflict):
    from tests.test_pinpoint_policy import context
    from backend.policy.pinpoint import generate
    c=context(tmp_path);scope={**c['scope'],'target_groups':['F/youth','M/youth'],'policy_context_version':'regional-policy-2'}
    batch=create(service,BatchRequest(request_id=uuid4(),task=task(dong_cd=c['dong_cd'],as_of=c['scope']['as_of']).model_dump(mode='json'),sex='all',age_group='youth'))
    proposals=[];versions=[]
    for index,sex in enumerate(('F','M'),1):
        policy={'id':'P1','title':'공식 사업','scope':'gangnam','support':'공식 지원 원문','eligibility':'지역 주민','agency':'공식 기관'}
        conditions={'서비스ID':'P1','JA0110':20,'JA0111':39,'JA0101':'Y','JA0102':'Y'}
        if index==2:
            if conflict=='support':policy['support']='변경된 공식 지원 원문'
            else:conditions['JA0111']=29
        versions.append({**deepcopy(policy),'supportConditions':deepcopy(conditions)})
        review={**deepcopy(c['need_reviews'][0]),'need_id':'N'+str(index),'target_group':sex+'/youth',
            'evidence_ids':['E'+str(index)],'policy_ids':['P1'],'citations':[{'policy_id':'P1','field':'support','quote':policy['support']}],
            'guidance':[deepcopy(policy)],'outreach_draft':{'text':'안내 제안'}}
        proposals.append({'task':{'sex':sex,'age_group':'youth'},'assessment':{
            'segments':[{'dong_cd':c['dong_cd'],'evidence_id':'E'+str(index),'stage':2,'value':.5,'index_name':'S1','source_period':'2025-09'}],
            'regional_context':{c['dong_cd']:deepcopy(c['regional_profile'])}},
            'policy_research':{'need_reviews':[review],'candidates':[{'policy':deepcopy(policy),'conditions':conditions,
                'evidence':{'field':'support','value':policy['support']},'detail_status':'live'}]}})
    before=deepcopy(proposals)
    monkeypatch.setattr(service.agents,'call',lambda *args:pytest.fail('source conflict must not invoke a model'))
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:pytest.fail('source conflict must not fetch more sources'))
    args=(service.policy_designer,batch['id'],batch['children'][0]['run_id'],scope,[{k:c[k] for k in ('dong_cd','dong_nm')}],proposals)
    result=generate(*args)
    assert len(result)==1
    held=result[0]
    assert held['owner_id']==batch['id'] and held['status']=='needs_evidence' and held['alternatives']==[]
    assert held['fallback_reason']=='policy_source_snapshot_conflict' and held['generation_mode']=='not_generated'
    evidence=held['evidence']
    assert evidence['source_conflicts']==['P1']
    assert all(version in evidence['conflicting_sources']['P1'] for version in versions)
    assert evidence['conflicting_need_reviews']==[p['policy_research']['need_reviews'][0] for p in before]
    assert {r['target_group'] for r in held['response_decisions']}=={'F/youth','M/youth'}
    assert all(r['decision']=='needs_evidence' and r['reason']=='policy_source_snapshot_conflict' and
        r['policy_ids']==[] and r['citations']==[] and r['guidance']==[] and r['outreach_draft'] is None for r in held['response_decisions'])
    assert proposals==before and generate(*args)==result
    with service.store.connection() as db:
        rows=db.execute('SELECT owner_id,body FROM policy_alternative_sets').fetchall()
        assert len(rows)==1 and rows[0][0]==batch['id'] and json.loads(rows[0][1])==held
        assert db.execute('SELECT COUNT(*) FROM llm_calls').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM policy_alternative_research').fetchone()[0]==0


# /ship Step 7 pass 2
# Value: protects=parent cancellation stops worker decisions and tools and prevents any subsequent native LLM reservation;
# fails_when=a cancelled worker starts another tool or decision, loses its explicit per-need hold, or reserves a new charged call;
# why_new=existing cancellation tests stop at conditional design, leaving the running research worker and reservation transaction unchecked;
# seam=none; no_claim=serial SQLite cancellation with fake decisions, not in-flight provider interruption or concurrent transaction stress.
@pytest.mark.parametrize('point',['before_decision','during_decision','during_tool'])
def test_cancelled_research_stops_worker_and_native_reservation(service,tmp_path,monkeypatch,point):
    import backend.agents.llm as llm
    from tests.test_regional_research import inputs
    delegated,_,_=inputs(tmp_path/'research');delegated.research_version='regional-research-2'
    batch=create(service,BatchRequest(request_id=uuid4(),task=task(dong_cd='11230001').model_dump(mode='json'),sex='F',age_group='youth'))
    run_id=batch['children'][0]['run_id'];decisions=[];tools=[]
    def cancel():
        with service.store.connection(write=True) as db:
            stored=json.loads(db.execute('SELECT body FROM regional_batches WHERE id=?',(batch['id'],)).fetchone()[0]);stored['cancelled']=True
            db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(stored),batch['id']))
    def decide(role,payload):
        decisions.append(role)
        if point=='during_decision':cancel()
        return {'action':'policy_refresh','query':'','page':1,'policy_id':None,'recommendations':[],'reason':'scripted first research decision'}
    def tool(name,args):
        tools.append(name);cancel()
        return {'status':'cached','coverage':{'source_complete':False}}
    monkeypatch.setattr(llm,'fake',decide)
    monkeypatch.setattr(service.policy_agent,'call_tool',tool)
    if point=='before_decision':cancel()
    result=service.policy_agent.run(run_id,'2026-10-24T09:00:00+09:00',delegated)
    assert result['status']=='cancelled' and result['recommendations']==[]
    assert result['need_reviews'][0]['decision']=='needs_evidence' and result['need_reviews'][0]['reason']=='cancelled'
    assert decisions==([] if point=='before_decision' else ['policy_decision'])
    assert tools==(['policy_refresh'] if point=='during_tool' else [])
    with service.store.connection() as db:
        calls=db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run_id,)).fetchone()[0]
        steps=db.execute('SELECT COUNT(*) FROM policy_steps WHERE run_id=?',(run_id,)).fetchone()[0]
    assert calls==len(decisions) and steps==len(tools)
    traces=deepcopy(service.store.traces(run_id))
    with pytest.raises(ValueError,match='cancelled'):
        service.agents.call(run_id,'2026-10-24T09:00:00+09:00','analysis',{'text':'new uncached call after cancellation'})
    assert service.store.traces(run_id)==traces
    with service.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run_id,)).fetchone()[0]==calls
    assert service.policy_agent.run(run_id,'2026-10-24T09:00:00+09:00',delegated)==result
    assert len(decisions)==calls and len(tools)==steps


# /ship Step 7 pass 2
# Value: protects=analogue research checks deadline and parent cancellation between queries while legacy no-deadline research still completes;
# fails_when=second or third provider queries start after a stop or a nullable legacy deadline stops ordinary three-query research;
# why_new=existing deadline tests cover model and field boundaries but never advance a stop during the first analogue query;
# seam=none; no_claim=scripted clock and analogue fixtures, not network interruption, live coverage or source suitability.
@pytest.mark.parametrize('stop',['deadline','cancelled','legacy_none'])
def test_analogue_research_stops_between_queries_and_keeps_legacy_deadline_optional(service,tmp_path,monkeypatch,stop):
    from types import SimpleNamespace
    from tests.test_pinpoint_policy import context
    from backend.policy.alternatives import research
    c=context(tmp_path);c['matching']=[{'evidence_id':'E1','needs':['relationship'],'uncovered_needs':['relationship']}]
    if stop=='legacy_none':c['design_version']='adaptation-1'
    batch=create(service,BatchRequest(request_id=uuid4(),task=task(dong_cd=c['dong_cd']).model_dump(mode='json'),sex='F',age_group='youth'))
    run_id=batch['children'][0]['run_id'];calls=[];clock=[0.]
    monkeypatch.setattr('backend.policy.alternatives.time',SimpleNamespace(time=lambda:clock[0]))
    def tool(name,args):
        assert name=='policy_analogues';calls.append(deepcopy(args));clock[0]=2.
        if stop=='cancelled':
            with service.store.connection(write=True) as db:
                stored=json.loads(db.execute('SELECT body FROM regional_batches WHERE id=?',(batch['id'],)).fetchone()[0]);stored['cancelled']=True
                db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(stored),batch['id']))
        return {'status':'evidence_available','total_matches':1,'analogues':[{'source':{
            'policy_id':'source-'+args['query'],'title':'공식 '+args['query'],'scope':'central',
            'fields':{'title':'공식 '+args['query'],'support':'공식 지원 원문'}}}]}
    monkeypatch.setattr(service.policy_agent,'call_tool',tool)
    before=deepcopy(c)
    if stop=='legacy_none':
        result=research(service.policy_designer,batch['id'],run_id,c,deadline=None)
        assert [r['query'] for r in result['research_steps']]==['고립','사회','상담']
        assert result['source_search_status']=='evidence_available'
        assert {s['policy_id'] for s in result['sources']}=={'P1','source-고립','source-사회','source-상담'}
    else:
        with pytest.raises(ValueError,match=stop):
            research(service.policy_designer,batch['id'],run_id,c,deadline=1. if stop=='deadline' else None)
        assert c==before
    assert [args['query'] for args in calls]==(['고립','사회','상담'] if stop=='legacy_none' else ['고립'])
    with service.store.connection() as db:
        cached=[json.loads(row[0]) for row in db.execute('SELECT body FROM policy_alternative_research WHERE owner_id=?',(batch['id'],))]
        assert len(cached)==len(calls) and all(row['status']=='evidence_available' for row in cached)
        assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run_id,)).fetchone()[0]==0
    trace_calls=[row for row in service.store.traces(run_id) if row['kind']=='tool_call']
    assert len(trace_calls)==len(calls)
