from copy import deepcopy
import json
from pathlib import Path
import pytest
from backend.policy.agent import PolicyTask
from backend.policy.research_contracts import NeedReview,validate_reviews
from backend.policy.pinpoint import generate
from tests.test_graph import service,scenario
from tests.test_regional_research import inputs
from tests.test_pinpoint_policy import context
from eval.alternative_quality import quality

CASES=json.loads((Path(__file__).resolve().parents[1]/'eval/fixtures/pinpoint-policy-cases.json').read_text())['cases']


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_fixed_response_cases_do_not_force_three(service,tmp_path,case):
    task,result,row=inputs(tmp_path);policy=result['recommendations'][0]['policy']
    policy.update(title='생성 정책',scope='central')
    need=task.needs[0];need.queries=['고립'];row['search_query']='고립';result['completed_queries']=['고립'];result['completed_searches']=[{'query':'고립','scopes':task.scopes}]
    c=context(tmp_path);c['regional_profile']=task.regional_profiles[0]
    change=case['change']
    if change=='personal_unknown':row['missing_evidence']=['개인 소득·실제 잔여 정원 확인']
    if change=='adapt':row.update(decision='adapt_existing',unmet_requirements=['야간 운영 미제공'])
    if change in ('new_design','incomplete_search','missing_context'):row.update(decision='new_design_needed',policy_ids=[],citations=[])
    if change=='incomplete_search':result.update(search_complete_within_scope=False,completed_queries=[],completed_searches=[])
    if change=='missing_eligibility':policy['eligibility']=''
    if change=='stale':result['coverage']={'stale':True};result['recommendations'][0]['detail_status']='cached'
    if change=='missing_context':task.regional_profiles=[];c['regional_profile']=None
    rejected=False
    try:reviews=validate_reviews([NeedReview(**row)],task,result)
    except ValueError:
        rejected=True;reviews=[{**row,'decision':'needs_evidence','guidance':[],'target_group':need.target_group,'need':need.need,'evidence_ids':need.evidence_ids}]
    assert rejected==case['review_rejected']
    c['need_reviews']=reviews;c['sources'][0]['fields']={k:v for k,v in policy.items() if k in ('support','eligibility','criteria') and v}
    run=service.register(scenario('monthly'));scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    body=generate(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
    assert body['status']==case['expected_status'],body.get('fallback_reason')
    assert len(body['alternatives'])==case['expected_alternatives']
    report=quality([body]);assert report['conditional_contract_pass_sets']==1
    assert report['grounding_eligible']==0  # Scripted fixture never receives a model-quality score.
    if body['status']=='reuse_existing':assert report['design_requested_sets']==0


def generated(service,tmp_path):
    c=context(tmp_path);run=service.register(scenario('monthly'));scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    return generate(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]


def test_renamed_copies_and_swapped_region_facts_do_not_pass_contract(service,tmp_path):
    body=generated(service,tmp_path);broken=deepcopy(body)
    for i,a in enumerate(broken['alternatives']):a.update(title='다른 동 '+str(i),proposed_service='동일한 운영 내용')
    assert quality([broken])['conditional_contract_pass_sets']==0
    broken=deepcopy(body);broken['alternatives'][0]['context_links'][0]['fact_id']='region-unobserved'
    report=quality([broken]);assert not report['rows'][0]['context_link_valid'] and report['conditional_contract_pass_sets']==0


def test_new_generation_records_its_actual_input_not_reconstructed_compaction(service,tmp_path):
    from backend.tools.indicators import digest
    body=generated(service,tmp_path)
    with service.store.connection() as db:
        calls=[json.loads(r[0]) for r in db.execute("SELECT body FROM llm_calls WHERE run_id=? AND role='policy_alternatives' AND status='ok'",(body['generation_run_id'],))]
    assert any(digest(c['input'])==body['model_input_hash'] for c in calls)


# /ship Step 7 pass 1 extension
# Value: protects=statistical review state and blocked IDs reach frozen design eligibility before generation;
# fails_when=numeric evidence bypasses an unreviewed or blocked statistics result;
# why_new=the original case supplied usable_for_design directly and could miss a broken context producer;
# seam=none; no_claim=synthetic proposals and fake generation, not statistical or policy judgment quality.
def test_statistics_hold_cannot_be_bypassed_by_numeric_facts_or_policy_reviews(service,tmp_path):
    c=context(tmp_path);c['facts'][0]['usable_for_design']=False
    run=service.register(scenario('monthly'));scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    body=generate(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
    assert body['alternatives']==[] and body['fallback_reason']=='regional_analysis_unreviewed'
    from backend.policy.pinpoint import context_for_region
    original=context(tmp_path/'producer');dong={k:original[k] for k in ('dong_cd','dong_nm')}
    scope={**original['scope'],'policy_context_version':'regional-policy-2'}
    for status,blocked,usable in (('reviewed',[],True),('reviewed',['E1'],False),('needs_human',[],False),(None,[],False)):
        proposal={'task':{'sex':'F','age_group':'youth'},'workflow':{'statistics':{'status':status,'blocked_evidence_ids':blocked}},
            'assessment':{'segments':[{'dong_cd':original['dong_cd'],'evidence_id':'E1','stage':2,'value':.5,
                'index_name':'S1','source_period':'2025-09','source_bands':{}}],
                'regional_context':{original['dong_cd']:original['regional_profile']},'metadata':{}},
            'policy_research':{'need_reviews':deepcopy(original['need_reviews'])}}
        before=deepcopy(proposal);frozen=context_for_region(dong,scope,[proposal])
        assert proposal==before and frozen['facts'][0]['usable_for_design'] is usable
        assert frozen['missing_groups']==([] if usable else ['F/youth'])
        frozen['sources']=deepcopy(original['sources'])
        run=service.register(scenario('monthly'))
        result=generate(service.policy_designer,run.id,run.id,scope,[dong],[],contexts={dong['dong_cd']:frozen})[0]
        assert len(result['alternatives'])==(3 if usable else 0)
        if not usable:
            assert result['fallback_reason']=='regional_analysis_unreviewed'
            with service.store.connection() as db:
                assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run.id,)).fetchone()[0]==0


def test_expired_deadline_stops_agent_and_generation_without_model_calls(service,tmp_path):
    from time import time
    from backend.policy.agent import PolicyTask
    run=service.register(scenario('monthly'))
    result=service.policy_agent.run(run.id,'2026-10-25',PolicyTask(goal='검토'),deadline=time()-1)
    assert result['status']=='deadline'
    c=context(tmp_path);scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    body=generate(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c},deadline=time()-1)[0]
    assert body['alternatives']==[] and body['fallback_reason']=='deadline'
    with service.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run.id,)).fetchone()[0]==0


def test_one_failed_census_table_preserves_independent_household_facts(tmp_path):
    from backend.context.service import ContextService,ContextUnavailable
    from tests.test_regional_context_service import settings,request
    def fetch(endpoint,args):
        if args['tblId']!='DT_1JC1502':raise ContextUnavailable('provider_connection_failed')
        return [{'ORG_ID':'101','TBL_ID':'DT_1JC1502','PRD_SE':'A','PRD_DE':'2020','C1':'11230510','C1_NM':'신사동','ITM_ID':item,'UNIT_NM':'가구','DT':value} for item,value in [('T0','600'),('T1','200')]]
    report=ContextService(settings(tmp_path),fetch).profile(request())
    assert report['status']=='partial'
    facts={f['metric']:f for f in report['facts']}
    assert facts['general_households']['value']==600 and facts['one_person_households']['value']==200
    assert facts['total_population']['value'] is None and facts['total_population']['status']=='missing'


# /ship Step 7 pass 2 extension
# Value: protects=regional regeneration forwards a 120-second deadline while legacy jobs retain their old call contract;
# fails_when=regional work becomes unbounded or a legacy caller receives an unexpected deadline argument;
# why_new=the existing case asserted saved results/idempotency without the dispatcher deadline;
# seam=none; no_claim=local job dispatch with a captured generator, not model/provider timing acceptance.
def test_regeneration_preserves_new_contract_frozen_facts_and_shared_run(service,tmp_path,monkeypatch):
    from uuid import uuid4
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.policy.alternative_regeneration import router
    from backend.policy.alternatives import router as proposals_router
    source=generated(service,tmp_path)
    app=FastAPI();app.include_router(router(service));app.include_router(proposals_router(service.store));client=TestClient(app)
    identifier=str(uuid4());path=f"/policy-proposals/{source['owner_id']}/{source['dong_cd']}/regenerate"
    request={'request_id':identifier,'version':source['version'],'revision':0}
    assert client.post(path,json=request).status_code==202
    body=client.get('/policy-proposals/'+identifier).json()['sets'][0]
    assert body['proposal_version']=='regional-policy-2' and len(body['alternatives'])==3
    assert body['evidence']['regional_profile']==source['evidence']['regional_profile']
    assert body['generation_run_id']==source['generation_run_id'] and body['owner_id']==identifier
    assert client.post(path,json=request).status_code==202
    assert client.get('/policy-proposals/'+identifier).json()['sets'][0]==body
    import backend.policy.alternative_regeneration as regeneration
    captured=[]
    def generate(*args,**kwargs):captured.append((args,kwargs));return []
    monkeypatch.setattr('backend.policy.alternatives.generate',generate)
    monkeypatch.setattr(regeneration.time,'time',lambda:1000.)
    for regional in (True,False):
        saved=deepcopy(source)
        if not regional:saved.pop('proposal_version')
        job_id=str(uuid4());job={'id':job_id,'status':'pending','source':saved,'run_id':source['generation_run_id']}
        with service.store.connection(write=True) as db:db.execute('INSERT INTO policy_regenerations VALUES (?,?)',(job_id,json.dumps(job)))
        regeneration.execute(service,job_id)
        args,kwargs=captured[-1]
        assert args[1:4]==(job_id,source['generation_run_id'],source['scope'])
        assert kwargs['contexts'][source['dong_cd']]['regional_profile']==source['evidence']['regional_profile']
        if regional:assert kwargs['deadline']==1120.
        else:assert 'deadline' not in kwargs
        with service.store.connection() as db:
            assert json.loads(db.execute('SELECT body FROM policy_regenerations WHERE id=?',(job_id,)).fetchone()[0])['status']=='completed'


def test_short_regional_references_restore_before_statistics_validation(service,tmp_path,monkeypatch):
    from tests.test_workflow_agents import run_task
    from tests.test_context_analysis import profile
    from backend.agents.workflow import statistical_review
    from time import time
    import backend.agents.llm as llm
    run=run_task(service,dong_cd='11230001');proposal=service.approval(run.id)['proposal'];assessment=proposal['assessment']
    p=profile(tmp_path);assessment['regional_context']={p['request']['dong_cd']:p}
    assessment['metadata']['review_contract_version']='statistics-review-2'
    canonical=next(f['fact_id'] for f in p['facts'] if f['status']=='observed')
    original=llm.fake
    def fake(role,payload):
        output=original(role,payload)
        if role=='workflow_statistics':
            regional=payload['regional_context'];columns=regional['fact_columns']
            short=next(row[columns.index('fact_id')] for area in regional['areas'] for row in area['facts'] if row[columns.index('status')]=='observed')
            assert short.startswith('R') and len(short)<8
            output.update(action='finish',regional_notes=[{'fact_ids':[short],'implication':'가구 여건 검토','hypothesis':'접근 경로 확인','missing_evidence':['실제 수요 미확인']}])
        return output
    monkeypatch.setattr(llm,'fake',fake)
    result=statistical_review(service.agents,service.settings,run.id,'2026-10-25',assessment,{**proposal['workflow']['analysis'],'priority_evidence_ids':[r['evidence_id'] for r in assessment['segments'] if r['dong_cd']==p['request']['dong_cd']]},lambda *a:None,time()+60)
    assert result['status']=='reviewed',(result.get('error_type'),[(t['kind'],t['payload']) for t in service.store.traces(run.id,limit=1000) if t['kind']=='error'])
    assert result['regional_notes'][0]['fact_ids']==[canonical]


def test_expired_census_deadline_makes_no_provider_calls(service,monkeypatch):
    from time import time
    from uuid import uuid4
    from backend.context.orchestration import freeze
    from backend.context.service import ContextService
    from tests.test_regional_task import task
    calls=[]
    def fetch(*args):calls.append(args);raise AssertionError('expired request reached provider')
    monkeypatch.setattr(ContextService,'request',fetch)
    from pydantic import SecretStr
    service.settings.data_mode='local';service.settings.kosis_api_key=SecretStr('fixture-only')
    monkeypatch.setattr('backend.context.service.boundaries',lambda:({'features':[{'properties':{'dong_cd':'11230001','sgg':'11230','dong_nm':'생성 지역'}}]},{'subset_sha256':'fixture-boundary'}))
    report=freeze(service,str(uuid4()),task(dong_cd='11230001').model_dump(mode='json'),[{'dong_cd':'11230001'}],deadline=time()-1)['11230001']
    assert report['status']=='unavailable' and calls==[]
    assert all(f['status']=='missing' for f in report['facts'])


def test_many_long_policy_details_fit_without_losing_frozen_sources(service,tmp_path):
    from backend.policy.agent import PolicyTask
    from tests.test_context_analysis import profile
    task=PolicyTask(goal='기존 정책의 제공 내용과 지역 여건 검토',research_version='regional-research-1',regional_profiles=[profile(tmp_path)])
    policies=[{'id':'P'+str(i),'title':'정책 '+str(i),'scope':'central',**{field:'지역 주민을 위한 활동과 신청 조건 확인 '*80 for field in ('support','eligibility','criteria','application','deadline','contact','agency')}} for i in range(5)]
    observations=[{'action':{'action':'policy_details'},'arguments':{'policy_ids':[p['id'] for p in policies]},'result':{'items':[{'policy':p,'status':'live'} for p in policies]}}]
    payload=service.policy_agent.model_payload(task,observations,1)
    shown=payload['observations'][0]['result']['items']
    assert [r['policy']['id'] for r in shown]==[p['id'] for p in policies]
    assert all('policy_field' in r['policy']['field_view'] and len(r['policy']['support'])<len(p['support']) for r,p in zip(shown,policies))
    assert all(len(p['support'])>1000 for p in policies)
    assert len(payload['task']['regional_profiles']['areas'][0]['facts'])==len(task.regional_profiles[0]['facts'])


def test_mixed_reuse_and_adaptation_keeps_reuse_without_extra_drafts(service,tmp_path):
    c=context(tmp_path)
    reuse={**deepcopy(c['need_reviews'][0]),'need_id':'N2','decision':'reuse_existing','reason':'기존 사업 활용'}
    c['need_reviews'].append(reuse)
    run=service.register(scenario('monthly'))
    body=generate(service.policy_designer,run.id,run.id,{**c['scope'],'policy_context_version':'regional-policy-2'},[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
    assert len(body['alternatives'])==3 and body['response_decisions'][1]==reuse
    assert all(a['need_ids']==['N1'] for a in body['alternatives'])


# /ship Step 7 pass 1 extension
# Value: protects=paired review rejects locality/time/data-mode mismatches and hides review metadata while preserving its private key;
# fails_when=unmatched frozen selections are paired or reviewer/operator identifiers leak into blinded alternatives;
# why_new=the existing case checked only one month mismatch and top-level owner/arm absence;
# seam=none; no_claim=synthetic offline packet integrity and partial masking, not independent policy ratings.
def test_paired_packet_keeps_zero_sets_and_rejects_changed_problem_or_scope(service,tmp_path):
    from eval.alternative_quality import packet
    from backend.tools.indicators import digest
    current=generated(service,tmp_path);before=deepcopy(current)
    current.update(status='needs_evidence',alternatives=[],fallback_reason='budget_exhausted')
    before['alternatives'][0].update(operator_notes='PRIVATE_OPERATOR_NOTE',review={'operator':'PRIVATE_REVIEWER_ID'})
    pairs=[{'case_id':'synthetic-pair','baseline':before,'current':current}]
    original=deepcopy(pairs)
    review,key,template=packet(pairs)
    assert pairs==original
    assert review['independent_quality'] is None and len(review['rubric'])==6
    assert key['input_hash']==digest(pairs) and key['packet_hash']==digest(review)==template['packet_hash']
    assert {len(i['output']['alternatives']) for i in review['items']}=={0,3}
    assert all(i['regional_facts']==current['evidence']['regional_profile']['facts'] for i in review['items'])
    assert all('owner_id' not in i and 'arm' not in i for i in review['items'])
    assert all(set(r['scores'])==set(review['rubric']) and all(v is None for v in r['scores'].values()) for r in template['ratings'])
    assert any(i['output']['hold_reason'] for i in review['items'])
    blind_ids={i['blind_id'] for i in review['items']}
    assert blind_ids==set(key['mapping'])=={r['blind_id'] for r in template['ratings']}
    for identifier,entry in key['mapping'].items():
        source=pairs[entry['index']][entry['arm']]
        assert entry=={'case_id':'synthetic-pair','arm':entry['arm'],'index':0,'owner_id':source['owner_id'],
                      'version':source['version'],'revision':source['review_revision']}
        assert any(i['blind_id']==identifier for i in review['items'])
    assert 'PRIVATE_OPERATOR_NOTE' not in json.dumps(review) and 'PRIVATE_REVIEWER_ID' not in json.dumps(review)
    for item in review['items']:
        for alternative in item['output']['alternatives']:
            assert not {'id','strategy','generation_mode','evidence_status','review_status','review','operator_notes'}&set(alternative)
    for field in ('problem','scope'):
        changed=deepcopy(pairs)
        if field=='problem':changed[0]['current']['evidence']['facts'][0]['value']=.99
        else:changed[0]['current']['scope']['ym']='2025-08'
        with pytest.raises(ValueError):packet(changed)
    with pytest.raises(ValueError):packet(pairs+pairs)
    for field,value in (('sgg','32010'),('as_of','2026-10-25'),('target_groups',['M/youth']),
                        ('selected_week','2025-12-15'),('synthetic_future',True)):
        changed=deepcopy(pairs);changed[0]['current']['scope'][field]=value
        with pytest.raises(ValueError,match='same frozen selection'):packet(changed)
    for field,value in (('dong_cd','11230002'),('data_mode','local')):
        changed=deepcopy(pairs);changed[0]['current'][field]=value
        with pytest.raises(ValueError,match='same frozen selection'):packet(changed)
    for field,value in (('sgg','32010'),('dong_cd','11230002'),('as_of','2026-10-25')):
        changed=deepcopy(pairs);changed[0]['current']['evidence']['regional_profile']['request'][field]=value
        with pytest.raises(ValueError,match='regional profile differs'):packet(changed)
    absent=deepcopy(pairs);absent[0]['current']['evidence']['regional_profile']=None
    assert all(item['regional_facts']==[] for item in packet(absent)[0]['items'])


# /ship Step 7 pass 1 extension
# Value: protects=one frozen profile's changed household value reaches the actual recorded model packet with all other facts identical;
# fails_when=hash changes come only from new timestamps or the changed value is dropped before the model boundary;
# why_new=the existing variants fetched separate profiles and asserted only model-input hashes;
# seam=none; no_claim=fake-mode input propagation and explicit evidence hold, not semantic improvement or provider acceptance.
def test_equal_index_changed_profile_reaches_model_and_removed_profile_holds(service,tmp_path):
    from tests.test_context_analysis import replace
    from backend.tools.indicators import digest
    outputs=[];contexts=[];recorded=[];base=context(tmp_path/'frozen')
    baseline_value=next(f['value'] for f in base['regional_profile']['facts'] if f['metric']=='one_person_households')
    changed_value=baseline_value+100
    for variant in ('baseline','changed','removed'):
        c=deepcopy(base)
        if variant=='changed':
            replace(c['regional_profile'],'one_person_households',value=changed_value)
            c['regional_profile']['input_hash']=digest({k:v for k,v in c['regional_profile'].items() if k!='input_hash'})
        if variant=='removed':c['regional_profile']=None
        contexts.append(deepcopy(c));run=service.register(scenario('monthly'))
        outputs.append(generate(service.policy_designer,run.id,run.id,{**c['scope'],'policy_context_version':'regional-policy-2'},[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0])
        with service.store.connection() as db:
            calls=[json.loads(row[0]) for row in db.execute("SELECT body FROM llm_calls WHERE run_id=? AND role='policy_alternatives' AND status='ok'",(run.id,))]
        if variant=='removed':assert calls==[]
        else:
            matches=[call['input'] for call in calls if digest(call['input'])==outputs[-1]['model_input_hash']]
            assert len(matches)==1
            recorded.append(matches[0])
    assert contexts[0]['facts']==contexts[1]['facts']==contexts[2]['facts']
    assert outputs[0]['status']==outputs[1]['status']=='draft'
    assert outputs[0]['model_input_hash']!=outputs[1]['model_input_hash']
    assert base==contexts[0]
    assert [f for f in contexts[0]['regional_profile']['facts'] if f['metric']!='one_person_households']==[
        f for f in contexts[1]['regional_profile']['facts'] if f['metric']!='one_person_households']
    values=[]
    for payload in recorded:
        regional=payload['regional_profile'];columns=regional['fact_columns']
        values.append(next(row[columns.index('value')] for area in regional['areas'] for row in area['facts']
                           if row[columns.index('metric')]=='one_person_households'))
    assert values==[baseline_value,changed_value]
    assert recorded[0]['facts']==recorded[1]['facts']
    assert outputs[2]['status']=='needs_evidence' and outputs[2]['alternatives']==[]
    # Scripted output is not evidence of a semantic improvement; this checks input propagation only.


# /ship Step 7 pass 2 addition
# Value: protects=mixed zero/three/legacy denominators and exact multiline quote, reviewed-fact and regional-link eligibility;
# fails_when=useful zero sets count as failed requests or unsupported/unreviewed evidence receives grounding credit;
# why_new=existing cases assert single sets and design validation, not mixed quality aggregation or its own guards;
# seam=none; no_claim=synthetic stored-set arithmetic/linkage, not actual model quality or independent ratings.
def test_quality_mixed_denominators_and_grounding_boundaries(service,tmp_path):
    from tests.test_alternative_quality import proposals
    from backend.tools.indicators import digest
    draft=generated(service,tmp_path)
    draft['evidence']['sources'][0]['fields']['support']='관계 활동\r\n후속 상담'
    for alternative in draft['alternatives']:
        alternative.update(generation_mode='llm',evidence_status='supported')
        alternative['source_elements'][0]['quote']='관계 활동\n후속 상담'
    reuse=deepcopy(draft);reuse.update(owner_id='reuse-owner',status='reuse_existing',alternatives=[])
    for review in reuse['response_decisions']:review['decision']='reuse_existing'
    hold=deepcopy(draft);hold.update(owner_id='held-owner',status='needs_evidence',alternatives=[])
    for review in hold['response_decisions']:review['decision']='needs_evidence'
    sets=[draft,reuse,hold,*proposals(service)];before=deepcopy(sets);report=quality(sets)
    assert {key:report[key] for key in ('sets','conditional_sets','design_requested_sets','reuse_sets','evidence_hold_sets',
        'conditional_contract_pass_sets','exactly_three','alternatives','grounding_eligible')}=={
        'sets':4,'conditional_sets':3,'design_requested_sets':2,'reuse_sets':1,'evidence_hold_sets':1,
        'conditional_contract_pass_sets':3,'exactly_three':2,'alternatives':6,'grounding_eligible':3}
    assert sets==before and report['input_hash']==digest(sets)
    assert all(axis['value'] is None for row in report['rows'] for axis in row['rubric'].values())
    assert all(row['citation_match'] and row['context_link_valid'] and row['regional_link_valid'] for row in report['rows'][:3])
    for case in ('bad_quote','unreviewed_fact','missing_regional_fact'):
        broken=deepcopy(draft)
        if case=='bad_quote':broken['alternatives'][0]['source_elements'][0]['quote']='원문에 없는 지급 약속'
        elif case=='unreviewed_fact':broken['evidence']['facts'][0]['usable_for_design']=False
        else:
            linked=broken['alternatives'][0]['context_links'][0]['fact_id']
            next(f for f in broken['evidence']['regional_profile']['facts'] if f['fact_id']==linked)['status']='missing'
        invalid=quality([broken]);row=invalid['rows'][0]
        assert invalid['conditional_contract_pass_sets']==0 and not row['grounding_eligible']
        assert not row[{'bad_quote':'citation_match','unreviewed_fact':'regional_link_valid','missing_regional_fact':'context_link_valid'}[case]]


# /ship Step 7 pass 2 addition
# Value: protects=offline packet CLI creates three hash-bound blank review artifacts, rejects bad inputs and preserves existing outputs;
# fails_when=invalid IDs publish packets, rubric guidance is omitted or a rerun overwrites prior review material;
# why_new=the packet function test bypasses argument parsing and filesystem publication;
# seam=none; no_claim=synthetic local files and blank templates, not independent ratings or provider/model acceptance.
def test_packet_cli_binds_artifacts_and_refuses_invalid_or_existing_outputs(service,tmp_path,monkeypatch,capsys):
    import sys
    from eval.alternative_quality import main
    from backend.tools.indicators import digest
    source=generated(service,tmp_path/'source');pairs=[{'case_id':'offline-case','baseline':source,'current':deepcopy(source)}]
    input_file=tmp_path/'pairs.json';input_file.write_text(json.dumps(pairs));output=tmp_path/'packet'
    monkeypatch.setattr(sys,'argv',['policy-packet',str(input_file),'--output',str(output)])
    main();assert capsys.readouterr().out.strip()==str(output)
    assert {p.name for p in output.iterdir()}=={'review-packet.json','private-key.json','ratings-template.json'}
    review=json.loads((output/'review-packet.json').read_text());key=json.loads((output/'private-key.json').read_text());template=json.loads((output/'ratings-template.json').read_text())
    assert key['input_hash']==template['input_hash']==review['input_hash']==digest(pairs)
    assert key['packet_hash']==template['packet_hash']==digest(review)
    assert set(review['rating_scale'])=={'1','2','3','4','5'} and all(review['rating_scale'].values())
    assert all(text in review['rating_instructions'] for text in ('null','0안','2명'))
    assert review['independent_quality'] is None and template['reviewers']==[]
    assert all(all(score is None for score in row['scores'].values()) and row['reviewer'] is None for row in template['ratings'])
    saved={p.name:p.read_bytes() for p in output.iterdir()}
    with pytest.raises(FileExistsError):main()
    assert {p.name:p.read_bytes() for p in output.iterdir()}==saved
    invalid_inputs=[None,[],[{'case_id':'','baseline':source,'current':source}],
        [{'case_id':7,'baseline':source,'current':source}],pairs+pairs]
    for index,invalid in enumerate(invalid_inputs):
        destination=tmp_path/('invalid-'+str(index));input_file.write_text(json.dumps(invalid))
        monkeypatch.setattr(sys,'argv',['policy-packet',str(input_file),'--output',str(destination)])
        with pytest.raises(SystemExit) as stopped:main()
        assert stopped.value.code==2 and not destination.exists()
        assert 'error:' in capsys.readouterr().err
    input_file.write_text('{');destination=tmp_path/'malformed'
    monkeypatch.setattr(sys,'argv',['policy-packet',str(input_file),'--output',str(destination)])
    with pytest.raises(SystemExit) as stopped:main()
    assert stopped.value.code==2 and not destination.exists()


# /ship Step 7 pass 2 addition
# Value: protects=grounding admits only the matching recorded run/input/live explanation and replays without another judge call;
# fails_when=another run, changed packet, fake call or changed rationale authorizes a grounding score;
# why_new=the producer-hash test never exercises the evaluator's recorded-call selection;
# seam=none; no_claim=synthetic ledger rows and fake judge/metric modules; no actual RAGAS score, provider, model or spend.
def test_grounding_requires_exact_recorded_generation_provenance(service,tmp_path,monkeypatch):
    import asyncio
    import sys
    from types import ModuleType,SimpleNamespace
    from uuid import uuid4
    from backend.tools.indicators import digest
    from eval.alternative_grounding import evaluate
    source=generated(service,tmp_path);samples=[];judges=[]
    class Judge:
        def __init__(self,*args):self.run_id='offline-mock-judge';judges.append(self)
        def finish(self,failed):self.failed=failed
    class Metric:
        def __init__(self,llm):self.llm=llm
        async def single_turn_ascore(self,sample):samples.append(sample);return .75
    ragas=ModuleType('ragas');ragas.SingleTurnSample=lambda **kwargs:SimpleNamespace(**kwargs)
    metrics=ModuleType('ragas.metrics');metrics.Faithfulness=Metric
    judge_module=ModuleType('eval.ragas_judge');judge_module.BudgetedJudge=Judge
    monkeypatch.setitem(sys.modules,'ragas',ragas);monkeypatch.setitem(sys.modules,'ragas.metrics',metrics)
    monkeypatch.setitem(sys.modules,'eval.ragas_judge',judge_module)
    def forbidden(*args,**kwargs):raise AssertionError('offline provenance test must not call a model')
    monkeypatch.setattr(service.agents,'call',forbidden)
    for variant in ('match','other_run','other_input','fake_call','changed_rationale'):
        body=deepcopy(source);body.update(owner_id=str(uuid4()),generation_mode='llm',llm_mode='live')
        for alternative in body['alternatives']:alternative.update(generation_mode='llm',evidence_status='supported')
        expected_input={'recorded_policy_packet':variant};body['model_input_hash']=digest(expected_input)
        metadata={'mode':'fake' if variant=='fake_call' else 'live',
            'input':{'different_packet':variant} if variant=='other_input' else expected_input,
            'output':{'alternatives':[{'strategy':a['strategy'],'rationale':'changed after generation' if variant=='changed_rationale' else a['rationale']} for a in body['alternatives']]}}
        ledger_run=service.register(scenario('monthly')).id if variant=='other_run' else body['generation_run_id']
        with service.store.connection(write=True) as db:
            db.execute('INSERT INTO policy_alternative_sets VALUES (?,?,?)',(body['owner_id'],body['dong_cd'],json.dumps(body)))
            db.execute('INSERT INTO llm_calls VALUES (?,?,?,?,?,?)',(ledger_run,'offline-provenance-'+variant,'policy_alternatives','ok',0.,json.dumps(metadata)))
        start_samples=len(samples);start_judges=len(judges)
        result=asyncio.run(evaluate(service.store,service.settings,body['owner_id']))
        if variant=='match':
            assert len(samples)-start_samples==3 and len(judges)-start_judges==1
            assert all(row['state']=='evaluated' and row['value']==.75 for row in result['rows'])
            assert all(json.loads(sample.retrieved_contexts[0])==expected_input for sample in samples[start_samples:])
            assert {sample.response for sample in samples[start_samples:]}=={a['rationale'] for a in body['alternatives']}
            assert judges[-1].failed is False
        else:
            assert len(samples)==start_samples and len(judges)==start_judges
            assert result['judge_run_id'] is None
            assert all(row['state']=='not_evaluated' and row['value'] is None for row in result['rows'])
        assert asyncio.run(evaluate(service.store,service.settings,body['owner_id']))==result
        assert len(samples)==start_samples+(3 if variant=='match' else 0)
