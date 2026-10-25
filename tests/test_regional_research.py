from copy import deepcopy
import pytest
from backend.policy.agent import PolicyTask
from backend.policy.research_contracts import NeedReview,validate_reviews
from tests.test_context_analysis import profile


def inputs(tmp_path):
    p=profile(tmp_path);f=p['facts'][0]['fact_id']
    task=PolicyTask(goal='지역 관계 지원 검토',research_version='regional-research-1',regional_profiles=[p],needs=[{
        'need_id':'N1','target_group':'F/youth','need':'relationship','evidence_ids':['E1'],
        'requirements':['관계 활동 제공'],'verified_gaps':['야간 운영 미제공']}])
    policy={'id':'P1','scope':'gangnam','support':'관계 활동 제공','eligibility':'지역 주민','application':'방문 신청','deadline':'상시','contact':'담당 부서','agency':'공식 기관'}
    result={'recommendations':[{'policy':policy,'detail_status':'live','conditions':{'서비스ID':'P1','JA0101':'Y','JA0102':'Y','JA0110':0,'JA0111':120}}],'search_complete_within_scope':True}
    row={'need_id':'N1','decision':'reuse_existing','policy_ids':['P1'],'citations':[{'policy_id':'P1','field':'support','quote':'관계 활동 제공'}],
         'regional_fact_ids':[f],'unmet_requirements':[],'reason':'공식 활동 제공 내용이 검토 요건에 대응','missing_evidence':['개인 소득 자격과 정원은 신청 전 확인']}
    return task,result,row


def test_existing_policy_guidance_and_partial_material_gap(tmp_path):
    task,result,row=inputs(tmp_path)
    output=validate_reviews([NeedReview(**row)],task,result)[0]
    assert output['decision']=='reuse_existing' and output['guidance'][0]['application']=='방문 신청'
    assert not output['individual_eligibility_verified'] and not output['capacity_verified']
    row.update(decision='adapt_existing',unmet_requirements=['야간 운영 미제공'])
    assert validate_reviews([NeedReview(**row)],task,result)[0]['decision']=='adapt_existing'
    row['unmet_requirements']=['개인 소득 미확인']
    with pytest.raises(ValueError,match='verified material gap'):validate_reviews([NeedReview(**row)],task,result)


# /ship Step 7 pass 2 extension
# Value: protects=unique need identities and substantive policy evidence are required for local reuse;
# fails_when=duplicate needs or title-only citations can authorize a checked local benefit;
# why_new=earlier rejection cases covered invented IDs and altered quotes, not those admission boundaries;
# seam=none; no_claim=synthetic contract inputs, not semantic suitability or actual policy absence.
def test_search_failures_and_unverified_quotes_cannot_trigger_new_policy(tmp_path):
    task,result,row=inputs(tmp_path)
    for changes in ({'citations':[{'policy_id':'P1','field':'support','quote':'허위 지원'}]}, {'regional_fact_ids':['invented']}, {'policy_ids':['unknown']}, {'decision':'reuse_existing','unmet_requirements':['부족']}):
        with pytest.raises(ValueError):validate_reviews([NeedReview(**{**row,**changes})],task,result)
    result['search_complete_within_scope']=False
    row.update(decision='new_design_needed',policy_ids=[],citations=[])
    with pytest.raises(ValueError,match='incomplete search'):validate_reviews([NeedReview(**row)],task,result)
    row.update(decision='needs_evidence')
    assert validate_reviews([NeedReview(**row)],task,result)[0]['decision']=='needs_evidence'
    with pytest.raises(ValueError):validate_reviews([],task,result)
    task,result,row=inputs(tmp_path/'substantive')
    result['recommendations'][0]['policy']['title']='확인한 공식 사업'
    for citations in ([],[{'policy_id':'P1','field':'title','quote':'확인한 공식 사업'}]):
        with pytest.raises(ValueError,match='substantive'):
            validate_reviews([NeedReview(**{**row,'citations':citations})],task,result)
    with pytest.raises(ValueError,match='duplicate research need'):
        PolicyTask.model_validate({**task.model_dump(),'needs':[task.needs[0].model_dump()]*2})


def test_newline_equivalence_and_all_checked_details_are_available(tmp_path):
    task,result,row=inputs(tmp_path)
    result['recommendations'][0]['policy']['support']='관계\r\n활동 제공'
    row['citations'][0]['quote']='관계\n활동 제공'
    assert validate_reviews([NeedReview(**row)],task,result)
    checked=deepcopy(result['recommendations'][0]);checked['policy']['scope']='central'
    result['recommendations']=[]
    observations=[{'action':{'action':'policy_detail'},'result':checked}]
    assert validate_reviews([NeedReview(**row)],task,result,observations)


def test_invalid_optional_field_is_rejected_cleanly_and_prior_queries_stay_complete(tmp_path):
    task,result,row=inputs(tmp_path)
    result['recommendations'][0]['policy']['deadline']=None
    row['citations']=[{'policy_id':'P1','field':'deadline','quote':'임의 기한'}]
    with pytest.raises(ValueError,match='citation'):validate_reviews([NeedReview(**row)],task,result)
    from types import SimpleNamespace
    from backend.policy.agent import PolicyAgent
    coverage={'source_complete':True,'stale':False,'last_attempt':{'status':'success'}}
    def search(query,total,next_page):return {'action':{'action':'policy_search'},'arguments':{'query':query,'scopes':['central'],'page':1},'result':{'coverage':coverage,'total':total,'next_page':next_page,'items':[]}}
    output=PolicyAgent.finish(SimpleNamespace(settings=SimpleNamespace(llm_mode='fake')),'completed',[],[search('고립',0,None),search('상담',5,2)])
    assert output['completed_queries']==['고립'] and not output['search_complete_within_scope']

    # /ship Step 7 pass 1 extension
    # Value: protects=completed need queries remain bound to their actual delegated jurisdictions;
    # fails_when=a complete query in a different scope authorizes local new design;
    # why_new=the previous assertion covered different query text, not identical text in different scopes;
    # seam=none; no_claim=synthetic scoped search observations, not exhaustive real policy discovery.
    task.needs[0].queries=['관계']
    task.scopes=['gangnam']
    row.update(decision='new_design_needed',policy_ids=[],citations=[],search_query='관계')
    complete=search('관계',0,None)
    incomplete=search('관계',2,2);incomplete['arguments']['scopes']=['gangnam']
    output=PolicyAgent.finish(SimpleNamespace(settings=SimpleNamespace(llm_mode='fake')),'completed',[],[complete,incomplete])
    assert output['completed_searches']==[{'query':'관계','scopes':['central']}]
    assert not output['search_complete_within_scope']
    with pytest.raises(ValueError,match='incomplete search'):
        validate_reviews([NeedReview(**row)],task,output)
    complete['arguments']['scopes']=['gangnam']
    output=PolicyAgent.finish(SimpleNamespace(settings=SimpleNamespace(llm_mode='fake')),'completed',[],[complete])
    assert validate_reviews([NeedReview(**row)],task,output)[0]['decision']=='new_design_needed'


# /ship Step 7 pass 1
# Value: protects=only current government policies covering the requested sex, ages and district become existing guidance;
# fails_when=wrong or missing material target conditions, stale records or expired offers are promoted;
# why_new=prior research cases used only a valid all-age policy and did not challenge target or date metadata;
# seam=none; no_claim=official-condition-shaped fixtures; no live API acceptance or semantic eligibility assessment.
def test_government_policy_target_and_time_checks_keep_material_unknowns_on_hold(tmp_path):
    task,result,row=inputs(tmp_path)
    task.scopes=['central','seoul','gangnam']
    checked=validate_reviews([NeedReview(**row)],task,result)[0]
    assert checked['guidance'][0]['target_checks']['age_coverage']=='full'
    assert not checked['individual_eligibility_verified'] and not checked['capacity_verified']
    changes=[
        ('conditions',{'서비스ID':'P1','JA0101':'Y','JA0102':'N','JA0110':19,'JA0111':34}),
        ('conditions',{'서비스ID':'P1','JA0101':'Y','JA0102':'Y','JA0110':65,'JA0111':120}),
        ('conditions',None),
        ('conditions',{'서비스ID':'other','JA0102':'Y','JA0110':19,'JA0111':34}),
        ('conditions',{'서비스ID':'P1','JA0102':'unknown','JA0110':19,'JA0111':34}),
        ('conditions',{'서비스ID':'P1','JA0102':'Y','JA0110':True,'JA0111':34}),
        ('conditions',{'서비스ID':'P1','JA0102':'Y','JA0110':'19','JA0111':34}),
        ('conditions',{'서비스ID':'P1','JA0102':'Y','JA0110':35,'JA0111':19}),
        ('conditions',{'서비스ID':'P1','JA0102':'Y','JA0110':0,'JA0111':151}),
        ('scope','chuncheon'),('support',''),('eligibility',''),
        ('deadline','2026-10-23'),('deadline','2026년 10월 23일'),
        ('source_updated_at','2026.10.25'),('detail_status','cached')]
    for field,value in changes:
        broken=deepcopy(result)
        target=broken['recommendations'][0] if field in ('conditions','detail_status') else broken['recommendations'][0]['policy']
        target[field]=value
        with pytest.raises(ValueError):validate_reviews([NeedReview(**row)],task,broken)
        held={**row,'decision':'needs_evidence','policy_ids':[],'citations':[]}
        assert validate_reviews([NeedReview(**held)],task,broken)[0]['decision']=='needs_evidence'
    exact=deepcopy(result)
    exact['recommendations'][0]['conditions'].update(JA0110=19,JA0111=34)
    exact['recommendations'][0]['policy'].update(deadline='2026/10/24',source_updated_at='2026-10-24')
    assert validate_reviews([NeedReview(**row)],task,exact)[0]['decision']=='reuse_existing'
    partial=deepcopy(exact);partial['recommendations'][0]['conditions']['JA0110']=20
    with pytest.raises(ValueError,match='coverage_gap'):validate_reviews([NeedReview(**row)],task,partial)
    adaptation={**row,'decision':'adapt_existing','unmet_requirements':['야간 운영 미제공']}
    assert validate_reviews([NeedReview(**adaptation)],task,partial)[0]['guidance'][0]['target_checks']['age_coverage']=='partial'
    cached=deepcopy(exact);cached['recommendations'][0]['detail_status']='cached'
    cached['coverage']={'stale':False}
    assert validate_reviews([NeedReview(**row)],task,cached)[0]['decision']=='reuse_existing'


# /ship Step 7 pass 1
# Value: protects=catalog guidance uses official support and rechecks real age, jurisdiction, time and need filters;
# fails_when=curation notes authorize reuse or invalid and partially covered resources become full local benefits;
# why_new=matching tests cover the matcher but not the research agent's catalog-to-guidance admission;
# seam=none; no_claim=synthetic catalog entries; individual eligibility, capacity and provider availability stay unknown.
def test_catalog_guidance_rechecks_resource_contract_and_retains_conditional_limits(tmp_path):
    from backend.app.config import ROOT
    from backend.tools.catalog import load_catalog
    task,result,row=inputs(tmp_path)
    resource=load_catalog(ROOT/'data/sample/resources.csv')[0].model_dump(mode='json')
    resource.update(age_min=19,age_max=34,evidence='관계 활동 제공',
                    isolation_relevance='편집자가 붙인 관련성 메모',eligibility_tags=['income'])
    task.existing_resources=[resource]
    result['recommendations']=[]
    pid='catalog:'+resource['id']
    row.update(policy_ids=[pid],citations=[{'policy_id':pid,'field':'support','quote':'관계 활동 제공'}])
    output=validate_reviews([NeedReview(**row)],task,result)[0]
    guidance=output['guidance'][0]
    assert guidance['source_kind']=='catalog' and guidance['support']=='관계 활동 제공'
    assert guidance['application'] is None and guidance['contact'] is None
    assert guidance['target_checks']['condition_checks']['eligibility:income']=='unknown'
    assert not output['individual_eligibility_verified'] and not output['capacity_verified']
    for changes in ({'jurisdiction':['32010']},{'active':False},{'valid_until':'2026-10-23'},
                    {'collected_at':'2026-10-25T00:00:00+09:00'}, {'age_min':65,'age_max':120},
                    {'needs':['health']},{'verification':'caution'}):
        task.existing_resources=[{**resource,**changes}]
        with pytest.raises(ValueError):validate_reviews([NeedReview(**row)],task,result)
    task.existing_resources=[{**resource,'age_min':20}]
    with pytest.raises(ValueError,match='coverage_gap'):validate_reviews([NeedReview(**row)],task,result)
    adaptation={**row,'decision':'adapt_existing','unmet_requirements':['야간 운영 미제공']}
    assert validate_reviews([NeedReview(**adaptation)],task,result)[0]['guidance'][0]['target_checks']['eligible_age_ranges']==[(20,34)]
    task.existing_resources=[resource]
    wrong={**row,'citations':[{'policy_id':pid,'field':'support','quote':resource['isolation_relevance']}]}
    with pytest.raises(ValueError,match='citation'):validate_reviews([NeedReview(**wrong)],task,result)


# /ship Step 7 pass 1
# Value: protects=research worker receives source metadata and substantive details, persists tools and fails closed on bad context;
# fails_when=research uses previews as full evidence, drops source identity or calls the model with malformed or oversized inputs;
# why_new=legacy worker tests do not exercise versioned regional input, checked need reviews or malformed profile handling;
# seam=none; no_claim=scripted decisions and mocked government tool responses; no actual model judgment or provider acceptance.
# /ship Step 7 pass 2 extension
# Value: protects=batch research inputs retain official target conditions without changing frozen source inputs;
# fails_when=multi-detail projection drops target metadata or model compaction mutates stored facts or observations;
# why_new=the existing test exercised only one detail and did not compare regional input snapshots;
# seam=none; no_claim=scripted fixture protocol, not model interpretation or live provider target acceptance.
def test_research_worker_model_input_and_saved_tools_preserve_evidence(tmp_path,monkeypatch):
    from backend.app.config import ROOT,Settings
    from backend.app.contracts import Scenario
    from backend.events import EventStore
    from backend.graph import GraphService
    from backend.policy.agent import PolicyDecision
    task,result,row=inputs(tmp_path/'context')
    row['proposed_channel']='담당자 검토 후 구청 안내문 게시 제안'
    task.scopes=['gangnam'];task.needs[0].queries=['관계']
    graph=GraphService(EventStore(tmp_path/'events.sqlite3'),Settings(_env_file=None,llm_mode='fake',
        data_mode='sample',runtime_storage_root=tmp_path/'runtime',gov24_service_key=None))
    sim='2026-10-24T09:00:00+09:00'
    policy={**result['recommendations'][0]['policy'],'title':'공식 관계 사업'}
    detail={'status':'live','policy':policy,'conditions':result['recommendations'][0]['conditions']}
    coverage={'source_complete':True,'stale':False,'last_attempt':{'status':'success'}}
    calls=[]
    def tool(name,args):
        calls.append((name,args))
        if name=='policy_search':return {'items':[policy],'total':1,'next_page':None,'coverage':coverage}
        assert name=='policy_detail'
        return detail
    payloads=[]
    def call(run_id,sim_ts,role,payload):
        payloads.append(deepcopy(payload));observations=payload['observations']
        action='policy_search' if not observations else 'policy_detail' if len(observations)==1 else 'finish'
        return PolicyDecision(action=action,query='관계',page=1,policy_id='P1' if action=='policy_detail' else None,
            recommendations=[{'policy_id':'P1','field':'title','value':policy['title'],'explanation':'후보'}] if action=='finish' else [],
            need_reviews=[row] if action=='finish' else [],reason='scripted contract fixture')
    monkeypatch.setattr(graph.policy_agent,'call_tool',tool)
    monkeypatch.setattr(graph.agents,'call',call)
    run=graph.register(Scenario(id='regional-research',type='policy',sim_time=sim,payload=task.model_dump(mode='json')))
    output=graph.policy_agent.run(run.id,sim,task)
    assert output['research_version']=='regional-research-1' and output['status']=='completed'
    assert output['need_reviews'][0]['guidance'][0]['application']=='방문 신청'
    assert output['recommendations'][0]['conditions']==detail['conditions']
    assert output['recommendations'][0]['candidate_status']=='reference_only'
    assert output['recommendations'][0]['local_eligibility']=='not_established'
    draft=output['need_reviews'][0]['outreach_draft']
    assert draft['channel_proposal']==row['proposed_channel'] and not draft['dispatch_performed']
    assert all(text in draft['text'] for text in ('방문 신청','담당 부서','공식 기관'))
    final=payloads[-1]
    visible=final['observations'][-1]['result']['policy']
    assert visible['support']==policy['support'] and visible['eligibility']==policy['eligibility']
    original=task.regional_profiles[0]['facts'][0]
    shown=final['task']['regional_profiles']['areas'][0]['facts'][0]
    assert all(shown[k]==original.get(k) for k in ('source','source_table','source_items','source_dimensions','geography_code','geography_version','published_at'))
    before=len(calls)
    assert graph.policy_agent.run(run.id,sim,task)==output and len(calls)==before
    malformed=task.model_copy(update={'regional_profiles':[{}]})
    assert graph.policy_agent.run(run.id,sim,malformed)['status']=='context_input_limit'
    batch={'action':{'action':'policy_details'},'result':{'status':'complete','items':[detail]}}
    snapshot=deepcopy((task.model_dump(),batch))
    view=graph.policy_agent.model_payload(task,[batch],1)
    visible_batch=view['observations'][0]['result']['items'][0]
    assert visible_batch['conditions']==detail['conditions']
    assert visible_batch['policy']['support']==policy['support']
    assert visible_batch['policy']['application']==policy['application']
    assert (task.model_dump(),batch)==snapshot
    visible_batch['conditions']['JA0102']='N'
    assert (task.model_dump(),batch)==snapshot
    graph.settings.llm_max_input_bytes=1000
    with pytest.raises(ValueError,match='policy_context_limit'):
        graph.policy_agent.model_payload(task,[{'action':{'action':'policy_detail'},'result':detail}]*2,1)


# /ship Step 7 pass 1
# Value: protects=public requests cannot supply server-owned regional research data or create records before rejection;
# fails_when=any reserved field is accepted or rejected only after a run, workflow or tool record is stored;
# why_new=existing API tests validate policy scopes but did not cover the new internal-only research task fields;
# seam=none; no_claim=local FastAPI and SQLite; ordinary provider calls are mocked, and internal Supervisor wiring is later work.
def test_public_policy_api_rejects_server_owned_research_inputs_before_registration(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.config import Settings
    from backend.app.graph_routes import graph_router
    from backend.events import EventStore
    from backend.graph import GraphService
    graph=GraphService(EventStore(tmp_path/'events.sqlite3'),Settings(_env_file=None,llm_mode='fake',
        data_mode='sample',runtime_storage_root=tmp_path/'runtime',gov24_service_key=None))
    monkeypatch.setattr(graph.policy_agent,'call_tool',lambda *args:{'status':'unavailable','last_attempt':{'status':'failed'}})
    app=FastAPI();app.include_router(graph_router(graph))
    body={'id':'public-policy','type':'policy','sim_time':'2026-10-24T09:00:00+09:00','payload':{'goal':'지원 정책 조사','max_steps':1}}
    with TestClient(app) as client:
        for key,value in {'research_version':'regional-research-1','needs':[],
                          'regional_profiles':[],'statistical_notes':[],'existing_resources':[]}.items():
            response=client.post('/scenarios/run',json={**body,'payload':{**body['payload'],key:value}})
            assert response.status_code==422 and 'supplied by the server' in response.json()['detail']
            with graph.store.connection() as db:
                assert all(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0 for table in ('runs','workflows','policy_steps'))
        response=client.post('/scenarios/run',json=body)
        assert response.status_code==202
        with graph.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM workflows').fetchone()[0]==1


# /ship Step 7 pass 2
# Value: protects=one policy's material mismatch holds only its need while independently valid local guidance survives;
# fails_when=wrong-target policy is promoted, valid peer guidance disappears or raw references imply local eligibility;
# why_new=direct validator rejection did not exercise mixed decisions through the stored search/detail/finish worker;
# seam=none; no_claim=scripted model and synthetic government responses; no real eligibility or model-quality finding.
def test_research_worker_preserves_valid_need_when_another_policy_target_is_invalid(tmp_path,monkeypatch):
    from backend.app.config import Settings
    from backend.app.contracts import Scenario
    from backend.events import EventStore
    from backend.graph import GraphService
    from backend.policy.agent import PolicyDecision
    task,result,row=inputs(tmp_path/'context')
    task.scopes=['gangnam']
    second=task.needs[0].model_copy(update={'need_id':'N2','need':'emotional','evidence_ids':['E2']})
    task.needs.append(second)
    first_policy={**result['recommendations'][0]['policy'],'title':'지역 관계 활동'}
    second_policy={**first_policy,'id':'P2','title':'남성 대상 상담','support':'공식 상담 제공'}
    first_detail={'status':'live','policy':first_policy,'conditions':result['recommendations'][0]['conditions']}
    second_detail={'status':'live','policy':second_policy,'conditions':{'서비스ID':'P2','JA0101':'Y','JA0102':'N','JA0110':19,'JA0111':34}}
    second_row={**row,'need_id':'N2','policy_ids':['P2'],
        'citations':[{'policy_id':'P2','field':'support','quote':'공식 상담 제공'}]}
    graph=GraphService(EventStore(tmp_path/'events.sqlite3'),Settings(_env_file=None,llm_mode='fake',
        data_mode='sample',runtime_storage_root=tmp_path/'runtime',gov24_service_key=None))
    sim='2026-10-24T09:00:00+09:00'
    def tool(name,args):
        if name=='policy_search':
            return {'items':[first_policy,second_policy],'total':2,'next_page':None,
                'coverage':{'source_complete':True,'stale':False,'last_attempt':{'status':'success'}}}
        assert name=='policy_details' and args['policy_ids']==['P1','P2']
        return {'status':'complete','items':[first_detail,second_detail]}
    def call(run_id,sim_ts,role,payload):
        action=['policy_search','policy_details','finish'][len(payload['observations'])]
        return PolicyDecision(action=action,query='관계',page=1,policy_id=None,
            policy_ids=['P1','P2'] if action=='policy_details' else [],reason='scripted mixed-need fixture',
            recommendations=[{'policy_id':p['id'],'field':'title','value':p['title'],'explanation':'참고 후보'}
                for p in (first_policy,second_policy)] if action=='finish' else [],
            need_reviews=[row,second_row] if action=='finish' else [])
    monkeypatch.setattr(graph.policy_agent,'call_tool',tool)
    monkeypatch.setattr(graph.agents,'call',call)
    run=graph.register(Scenario(id='mixed-research',type='policy',sim_time=sim,payload=task.model_dump(mode='json')))
    output=graph.policy_agent.run(run.id,sim,task)
    reviews={r['need_id']:r for r in output['need_reviews']}
    assert output['status']=='needs_evidence'
    assert reviews['N1']['decision']=='reuse_existing' and reviews['N1']['guidance'][0]['id']=='P1'
    assert reviews['N2']['decision']=='needs_evidence' and reviews['N2']['guidance']==[]
    assert reviews['N2']['policy_ids']==[] and reviews['N2']['outreach_draft'] is None
    assert reviews['N2']['reason']=='policy_target_mismatch'
    assert len(output['recommendations'])==2
    assert all(r['candidate_status']=='reference_only' and r['local_eligibility']=='not_established'
        for r in output['recommendations'])
    with graph.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM policy_steps WHERE run_id=?',(run.id,)).fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0]==0


# /ship Step 7 pass 2
# Value: protects=catalog-only reuse and adaptation finish without a recommendation quota and retain copied outreach limits;
# fails_when=valid existing guidance reports incomplete solely for empty slots or catalog notes replace official support;
# why_new=prior tests validated catalog rows directly but did not run the real fake agent and its persisted result;
# seam=none; no_claim=real deterministic fake mode with synthetic catalog data; no actual LLM reasoning or availability.
def test_catalog_only_fake_research_completes_without_filling_recommendation_slots(tmp_path,monkeypatch):
    from backend.app.config import ROOT,Settings
    from backend.app.contracts import Scenario
    from backend.events import EventStore
    from backend.graph import GraphService
    from backend.policy.agent import PolicyDecision
    from backend.tools.catalog import load_catalog
    task,_,_=inputs(tmp_path/'context')
    task.scopes=['gangnam']
    resource=load_catalog(ROOT/'data/sample/resources.csv')[0].model_dump(mode='json')
    resource.update(age_min=19,age_max=34,jurisdiction=['11230'],evidence='공식 관계 활동 제공',
        isolation_relevance='편집자가 붙인 해설',eligibility_tags=['income'])
    task.existing_resources=[resource]
    graph=GraphService(EventStore(tmp_path/'events.sqlite3'),Settings(_env_file=None,llm_mode='fake',
        data_mode='sample',runtime_storage_root=tmp_path/'runtime',gov24_service_key=None))
    monkeypatch.setattr(graph.policy_agent,'call_tool',lambda *args:pytest.fail('catalog-only research must not fetch government data'))
    sim='2026-10-24T09:00:00+09:00'
    for index,(gaps,expected) in enumerate((([], 'reuse_existing'),(['야간 운영 미제공'],'adapt_existing'))):
        task.needs[0].verified_gaps=gaps
        run=graph.register(Scenario(id=f'catalog-research-{index}',type='policy',sim_time=sim,payload=task.model_dump(mode='json')))
        output=graph.policy_agent.run(run.id,sim,task)
        assert output['status']=='completed' and output['recommendations']==[]
        assert not output['search_complete_within_scope'] and not output['all_policies_known']
        review=output['need_reviews'][0]
        assert review['decision']==expected and review['guidance'][0]['support']==resource['evidence']
        assert review['unmet_requirements']==gaps
        assert review['outreach_draft']['channel_proposal'] and not review['outreach_draft']['dispatch_performed']
        assert resource['evidence'] in review['outreach_draft']['text']
        assert resource['isolation_relevance'] not in review['outreach_draft']['text']
        assert review['guidance'][0]['application'] is None and review['guidance'][0]['contact'] is None
        assert not review['individual_eligibility_verified'] and not review['capacity_verified']
        with graph.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=? AND status=?',(run.id,'ok')).fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM policy_steps WHERE run_id=?',(run.id,)).fetchone()[0]==0
    decision=PolicyDecision(action='finish',query='',page=1,policy_id=None,reason='checked catalog reference',
        recommendations=[{'policy_id':'catalog:'+resource['id'],'field':'support','value':resource['evidence'],'explanation':'참고 후보'}])
    candidate=graph.policy_agent.recommendations(decision,[],task)[0]
    assert candidate['evidence']['value']==resource['evidence'] and candidate['source_kind']=='catalog'
    assert candidate['candidate_status']=='reference_only' and candidate['detail_status']=='catalog_snapshot'
    decision.recommendations[0].value=resource['isolation_relevance']
    with pytest.raises(ValueError,match='invalid_evidence'):
        graph.policy_agent.recommendations(decision,[],task)


# /ship Step 7 pass 2
# Value: protects=every bounded research failure returns explicit per-need evidence holds without invented guidance;
# fails_when=input, model, tool or budget failures erase need identities or become completed available benefits;
# why_new=legacy status tests did not require structured holds on the versioned regional task;
# seam=none; no_claim=scripted failures and local SQLite; no production outage, real paid budget or provider acceptance.
def test_research_failures_keep_per_need_holds_and_safe_termination_reasons(tmp_path,monkeypatch):
    from backend.app.config import Settings
    from backend.app.contracts import Scenario
    from backend.events import EventStore
    from backend.graph import GraphService
    from backend.policy.agent import PolicyDecision
    task,_,_=inputs(tmp_path/'context')
    graph=GraphService(EventStore(tmp_path/'events.sqlite3'),Settings(_env_file=None,llm_mode='fake',
        data_mode='sample',runtime_storage_root=tmp_path/'runtime',gov24_service_key=None))
    sim='2026-10-24T09:00:00+09:00'
    for case,expected in [('context','context_input_limit'),('model','model_unavailable_or_budget'),
                          ('action','invalid_action'),('evidence','invalid_evidence'),('limit','step_limit'),
                          ('repeated','repeated_action'),('api','needs_evidence')]:
        current=task.model_copy(deep=True)
        if case=='context':current.regional_profiles=[{}]
        if case=='limit':current.max_steps=1
        def call(run_id,sim_ts,role,payload):
            if case=='model':raise ValueError('fixture private provider diagnostic')
            if case=='context':pytest.fail('invalid regional input must stop before the model')
            action='policy_detail' if case=='action' else 'finish' if case=='evidence' or case=='api' and payload['observations'] else 'policy_refresh'
            held={'need_id':'N1','decision':'needs_evidence','policy_ids':[],'citations':[],
                'regional_fact_ids':[],'unmet_requirements':[],'reason':'공식 API 조회가 완료되지 않았습니다.',
                'missing_evidence':['공식 자료 재조회 필요']}
            return PolicyDecision(action=action,query='',page=1,policy_id='unobserved' if case=='action' else None,
                recommendations=[{'policy_id':'invented','field':'title','value':'허위 사업','explanation':'invalid fixture'}]
                    if case=='evidence' else [],need_reviews=[held] if action=='finish' else [],reason='bounded failure fixture')
        monkeypatch.setattr(graph.agents,'call',call)
        monkeypatch.setattr(graph.policy_agent,'call_tool',lambda *args:{'status':'error','error':'TimeoutError'})
        run=graph.register(Scenario(id='research-failure-'+case,type='policy',sim_time=sim,payload=task.model_dump(mode='json')))
        output=graph.policy_agent.run(run.id,sim,current)
        assert output['status']==expected and output['research_version']=='regional-research-1'
        assert output['recommendations']==[] and not output['allocation_performed']
        assert len(output['need_reviews'])==1
        held=output['need_reviews'][0]
        assert held['need_id']=='N1' and held['target_group']=='F/youth' and held['evidence_ids']==['E1']
        assert held['decision']=='needs_evidence' and held['guidance']==[] and held['policy_ids']==[]
        assert held['outreach_draft'] is None and not held['individual_eligibility_verified'] and not held['capacity_verified']
        assert held['reason'] and held['missing_evidence']
        assert 'fixture private provider diagnostic' not in str(output)
