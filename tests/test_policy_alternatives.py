from copy import deepcopy
from uuid import uuid4
import pytest
from tests.test_graph import service,scenario
from tests.test_regional_task import task
from backend.policy.alternatives import templates,validate


def sets(service,owner):
    import json
    with service.store.connection() as db:return [json.loads(r[0]) for r in db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=?',(owner,))]


def test_always_three_even_when_budget_spent_and_replay_has_no_calls(service,monkeypatch):
    run=service.start(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    result=sets(service,run.id)
    assert result and all(len(s['alternatives'])==3 for s in result)
    assert all(not s['allocation_performed'] and not s['budget_approved'] for s in result)
    assert service.approval(run.id)['proposal']['policy_alternatives']['dong_count']==len(result)
    monkeypatch.setattr(service.agents,'call',lambda *args:pytest.fail('replay must not call'))
    first=result[0]
    assert service.policy_designer.propose(run.id,run.id,first['scope'],[{'dong_cd':first['dong_cd'],'dong_nm':first['dong_nm']}],[])==[first]


def test_empty_evidence_and_failed_model_are_explicit_concepts(service,monkeypatch):
    run=service.register(scenario());scope={'sgg':'11230','ym':'2025-09','as_of':'2026-10-23','target_groups':['M/youth','F/elderly']}
    dong={'dong_cd':'11230680','dong_nm':'검증동'}
    result=service.policy_designer.propose(run.id,run.id,scope,[dong],[])[0]
    assert result['generation_mode']=='template_fallback'
    for a in result['alternatives']:
        assert a['evidence_status']=='concept_only' and not a['citations'] and a['missing_evidence']
    context=result['evidence'];output=templates(context)
    output['alternatives'][0]['source_policy_ids']=['invented']
    with pytest.raises(ValueError,match='unknown policy'):validate(output,context)
    output=templates(context);output['alternatives'][0]['target_groups']=['outside']
    with pytest.raises(ValueError,match='unrequested'):validate(output,context)
    output=templates(context);output['alternatives'][0]['proposed_service']=output['alternatives'][1]['proposed_service']
    with pytest.raises(ValueError,match='duplicate'):validate(output,context)


def test_batch_creates_three_per_dong_not_per_cohort(service):
    from backend.regional_batch import create,execute,public,read
    from tests.test_regional_batch import request
    body=create(service,request());execute(service,body['id'])
    result=sets(service,body['id'])
    assert len(result)==len(body['dongs'])
    assert all(len(s['alternatives'])==3 and len(s['scope']['target_groups'])==8 for s in result)
    assert public(service,read(service,body['id']))['policy_proposals']['dong_count']==len(result)
    execute(service,body['id']);assert sets(service,body['id'])==result


def test_failed_known_scope_retains_three_concepts(service,monkeypatch):
    def fail(*args):raise ValueError('no observations')
    monkeypatch.setattr(service,'classify_node',fail)
    run=service.register(scenario('monthly',workflow_version='regional-workflow-1',task=task().model_dump(mode='json')))
    service.execute(run.id)
    assert service.store.get_run(run.id).status=='failed'
    assert sets(service,run.id) and all(s['generation_mode']=='template_fallback' for s in sets(service,run.id))


def test_model_and_tool_failure_preserve_three_and_cancellation_stops_next_dong(service,monkeypatch):
    from tests.test_workflow_agents import run_task
    from backend.regional_batch import create,execute,read
    from tests.test_regional_batch import request
    run=run_task(service);p=service.approval(run.id)['proposal']
    rows=p['assessment']['segments'];dong={'dong_cd':rows[0]['dong_cd'],'dong_nm':rows[0]['dong_nm']}
    scope={**p['task'],'target_groups':['M/youth']}
    from backend.tools.regional_resources import policy_gap
    for a in p['assignments']:
        a.update(recommendations=[],uncovered_needs=a['needs'],shortfall=3)
        a['policy_gap']=policy_gap(a)
    def fail(*args):raise RuntimeError('offline')
    monkeypatch.setattr(service.agents,'call',fail);monkeypatch.setattr(service.policy_agent,'call_tool',fail)
    result=service.policy_designer.propose(str(uuid4()),run.id,scope,[dong],[p])[0]
    assert result['generation_mode']=='template_fallback' and len(result['alternatives'])==3
    assert result['evidence']['source_search_status']=='unavailable'
    body=create(service,request());body['cancelled']=True
    import json
    with service.store.connection(write=True) as db:db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(body),body['id']))
    service.policy_designer.propose(body['id'],run.id,scope,body['dongs'],[])
    assert sets(service,body['id'])==[]


def test_invalid_alternative_does_not_discard_other_two(service,monkeypatch):
    from types import SimpleNamespace
    from tests.test_workflow_agents import run_task
    run=run_task(service);p=service.approval(run.id)['proposal'];row=next(r for r in p['assessment']['segments'] if r['value'] is not None and r['stage'] is not None)
    def call(run_id,sim,role,context):
        output=templates(context)
        for a in output['alternatives']:a['problem_evidence_ids']=[row['evidence_id']]
        output['alternatives'][0]['source_policy_ids']=['invented']
        return SimpleNamespace(model_dump=lambda:output)
    monkeypatch.setattr(service.agents,'call',call)
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:{'status':'unavailable'})
    result=service.policy_designer.propose(str(uuid4()),run.id,{**p['task'],'target_groups':[p['task']['sex']+'/'+p['task']['age_group']]},[{'dong_cd':row['dong_cd'],'dong_nm':row['dong_nm']}],[p])[0]
    assert result['generation_mode']=='mixed'
    assert [a['generation_mode'] for a in result['alternatives']]==['template_fallback','fixture','fixture']
    assert result['alternatives'][1]['evidence_status']=='partial'


def test_existing_candidate_still_triggers_targeted_research_and_caches(service,monkeypatch):
    from backend.policy.alternatives import research,model_context
    run=service.register(scenario());calls=[]
    def tool(name,args):
        calls.append(args)
        return {'status':'evidence_available','analogues':[{'source':{'policy_id':'reference-'+args['query'],'title':'돌봄 지원','scope':'seoul','source_url':'https://www.gov.kr/','checked_at':'2026-10-24','fields':{'title':'돌봄 지원','support':'방문 상담과 후속 연락','eligibility':'청년'}},'comparison':{'similarity_basis':'keyword_rank_only','differences':['전달 기관 미확인']}}]}
    monkeypatch.setattr(service.policy_agent,'call_tool',tool)
    context={'scope':{'sgg':'11230'},'target_groups':['M/youth'],'facts':[],'analyses':[],'statistics':[],
             'matching':[{'needs':['health','housing','economic','employment'],'uncovered_needs':['housing']}],
             'sources':[{'policy_id':'existing','title':'기존 후보','evidence':{'field':'title','value':'기존 후보'},'role':'existing_candidate'}],
             'design_version':'adaptation-1'}
    result=research(service.policy_designer,run.id,run.id,deepcopy(context))
    assert len(calls)==3 and calls[0]['query']=='주거' and calls[0]['target_group']=='남성 청년'
    assert len(result['sources'])==4 and result['sources'][1]['evidence']['field']=='support'
    research(service.policy_designer,run.id,run.id,deepcopy(context));assert len(calls)==3
    view=model_context(result)
    assert len(view['sources'])==3 and all('fields' in s for s in view['sources'])
    assert view['source_count_available']==4


def test_adaptation_quotes_must_match_actual_source_fields():
    context={'dong_nm':'동','target_groups':['M/youth'],'facts':[],
             'sources':[{'policy_id':'p1','fields':{'support':'방문 상담과 후속 연락'}}]}
    output=templates(context)
    output['alternatives'][0].update(source_policy_ids=['p1'],source_elements=[{'policy_id':'p1','field':'support','quote':'방문 상담'}],
        adaptations=[{'source_policy_ids':['p1'],'local_difference':'전달기관 미확인','proposed_change':'접근성이 낮은 집단 방문 예약','verification_needed':['협력기관 확인']}])
    assert validate(output,context)['alternatives'][0]['adaptations']
    output['alternatives'][0]['source_elements'][0]['quote']='월 50만원 지급'
    with pytest.raises(ValueError,match='not grounded'):validate(output,context)


def test_model_preview_budget_preserves_regional_facts_and_original_sources():
    from backend.policy.alternatives import model_context
    import json
    context={'target_groups':['M/youth'],'facts':[{'evidence_id':'e','target_group':'M/youth','value':1,'stage':3}],
        'analyses':[],'statistics':[],'matching':[],'design_version':'adaptation-1',
        'sources':[{'policy_id':str(i),'role':'analogue_not_local_eligibility','evidence':{'field':'support','value':'방문 상담'*200},'fields':{'support':'방문 상담'*200}} for i in range(8)],
        'model_view_budget_bytes':1800}
    view=model_context(context)
    assert len(json.dumps(view,ensure_ascii=False).encode())<=1800
    assert view['facts']==context['facts'] and len(context['sources'])==8


def test_regional_facts_over_budget_are_not_silently_truncated():
    from backend.policy.alternatives import model_context
    context={'facts':[{'evidence_id':'e','value':'x'*2000}], 'analyses':[], 'statistics':[], 'matching':[], 'sources':[], 'model_view_budget_bytes':200}
    with pytest.raises(ValueError,match='regional context exceeds'):model_context(context)


def test_exact_requested_group_label_maps_back_without_accepting_other_targets(service,monkeypatch):
    from types import SimpleNamespace
    from tests.test_workflow_agents import run_task
    run=run_task(service);proposal=service.approval(run.id)['proposal'];row=proposal['assessment']['segments'][0]
    def call(run_id,sim,role,context):
        output=templates(context)
        for a in output['alternatives']:
            a['target_groups']=[context['target_group_labels'][context['target_groups'][0]]]
            a['problem_evidence_ids']=['E1']
        output['alternatives'][2]['target_groups']=['청소년']
        return SimpleNamespace(model_dump=lambda:output)
    monkeypatch.setattr(service.agents,'call',call)
    monkeypatch.setattr(service.policy_agent,'call_tool',lambda *args:{'status':'unavailable'})
    scope={**proposal['task'],'target_groups':['M/youth']}
    result=service.policy_designer.propose(str(uuid4()),run.id,scope,[{'dong_cd':row['dong_cd'],'dong_nm':row['dong_nm']}],[proposal])[0]
    assert [a['generation_mode'] for a in result['alternatives']]==['fixture','fixture','template_fallback']
    assert result['alternatives'][0]['target_groups']==['M/youth']


def test_v4_assessed_stage_can_ground_policy_alternatives_without_continuous_value(service,monkeypatch):
    from types import SimpleNamespace
    from backend.policy.alternatives import generate

    target='F/60대+';evidence_id='v4-evidence'
    context={'dong_nm':'개포3동','target_groups':[target],'facts':[{'evidence_id':evidence_id,'target_group':target,'stage':2,'value':None,
        'methodology_version':'regional-workflow-2','assessment_status':'assessed','source_age_band':'60대+',
        'frame':'노년','source_stage':2,'source_stage_label':'관심','base_stage':2,'final_stage':2,'stage_adjustment':0,'priority_rank':7,
        'final_stage_label':'관심','card_week':'2025-12-15','card_source_age_bands':['60대','70대+'],'card_alarm_status':'none',
        'card_evidence':[{'source_age_band':'60대','baseline_status':'observed','v_ratio':1.1234,'n_ratio':None,'v_stage':1,'n_stage':0,'alarm_stage':0},
                         {'source_age_band':'70대+','baseline_status':'unavailable','v_ratio':None,'n_ratio':None,'v_stage':0,'n_stage':0,'alarm_stage':0}]}],
        'analyses':[],'statistics':[],'matching':[],'sources':[],'gap_contract_version':None}
    calls=[]

    def call(run_id,sim_ts,role,view):
        calls.append((role,view['facts']))
        output=templates(context)
        for alternative in output['alternatives']:
            alternative['problem_evidence_ids']=["E1"]
        return SimpleNamespace(model_dump=lambda:output)

    monkeypatch.setattr(service.agents,'call',call)
    dong={'dong_cd':'11230001','dong_nm':'개포3동','sgg':'11230'}
    scope={'sgg':'11230','ym':'2025-12','as_of':'2026-10-25','target_groups':[target],
           'selected_week':'2025-12-15','synthetic_future':False}
    result=generate(service.policy_designer,'v4-owner','v4-run',scope,[dong],[],contexts={dong['dong_cd']:context})[0]

    assert len(calls)==1 and calls[0][0]=='policy_alternatives'
    assert result['generation_mode']=='fixture'
    assert result['alternatives'][0]['problem_evidence_ids']==[evidence_id]
    assert result['evidence']['facts'][0]['value'] is None
    from backend.policy.alternative_export import sections,render_pdf,render_docx
    evidence_lines=[line for _,line in sections(result) if '연속 지수 미산출' in line]
    assert len(evidence_lines)==1 and all(value in evidence_lines[0] for value in ('여성 60대+','원천 연령 60대+','노년','기본 단계 2','2025-12-15','V 1.123배/1단계','N 기준선 없음/0단계','부분 기준선','동별 확인 순서 7'))
    from io import BytesIO
    from pypdf import PdfReader
    from zipfile import ZipFile
    pdf='\n'.join(page.extract_text() for page in PdfReader(BytesIO(render_pdf(sections(result)))).pages)
    with ZipFile(BytesIO(render_docx(sections(result)))) as archive:docx=archive.read('word/document.xml').decode()
    assert 'V 1.123배/1단계' in pdf and 'N 기준선 없음/0단계' in docx and '부분 기준선' in pdf and '2025-12-15' in docx
