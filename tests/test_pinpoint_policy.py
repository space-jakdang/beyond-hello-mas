from tests.test_graph import service
from copy import deepcopy
import pytest
from tests.test_context_analysis import profile
from backend.policy.pinpoint import validate,fixture_design,context_for_region


def context(tmp_path):
    p=profile(tmp_path)
    return {'dong_cd':'11230001','dong_nm':'생성 지역','scope':{'sgg':'11230','ym':'2025-09','as_of':'2026-10-24','target_groups':['F/youth']},
        'design_version':'pinpoint-1','target_groups':['F/youth'],'regional_profile':p,'missing_groups':[],
        'facts':[{'evidence_id':'E1','target_group':'F/youth','value':.5,'stage':2}],
        'analyses':[],'statistics':[],'matching':[],
        'sources':[{'policy_id':'P1','title':'생성 정책','role':'existing_candidate','evidence':{'field':'support','value':'관계 활동'},'fields':{'support':'관계 활동'}}],
        'need_reviews':[{'need_id':'N1','decision':'adapt_existing','target_group':'F/youth','need':'relationship','reason':'확인된 운영 요건 보완','missing_evidence':['현장 실행 조건'],'guidance':[],'evidence_ids':['E1']} ]}


# /ship Step 7 pass 1 extension
# Value: protects=alternatives use selected need evidence, substantive quotes and a known agency identity;
# fails_when=unrelated same-group evidence or an agency-free source authorizes a claimed operating agency;
# why_new=the original cases rejected unknown IDs but did not distinguish need ownership or agency identity;
# seam=none; no_claim=synthetic source contracts only, not semantic policy quality or agency participation.
def test_three_grounded_operating_choices_and_no_generic_success(tmp_path):
    c=context(tmp_path);output=fixture_design(c)
    assert len(validate(output,c)['alternatives'])==3
    for change in ('duplicate','unknown_fact','wrong_group','unknown_need','bad_quote','no_operation_difference'):
        broken=deepcopy(output);a=broken['alternatives'][0]
        if change=='duplicate':a['delivery_model']=broken['alternatives'][1]['delivery_model']
        elif change=='unknown_fact':a['context_links'][0]['fact_id']='invented'
        elif change=='wrong_group':a['target_groups']=['M/youth']
        elif change=='unknown_need':a['need_ids']=['invented']
        elif change=='bad_quote':a['source_elements'][0]['quote']='허위 내용'
        else:a['adaptations']=[]
        with pytest.raises(ValueError):validate(broken,c)
    for field,value in (('source_policy_ids',['unknown']),('agency_policy_ids',['unknown']),
                        ('source_elements',[]),('evaluation_design',None)):
        broken=deepcopy(output);broken['alternatives'][0][field]=value
        with pytest.raises(ValueError):validate(broken,c)
    unrelated=deepcopy(c)
    unrelated['facts'].append({'evidence_id':'E2','target_group':'F/youth','value':.7,'stage':3})
    wrong=deepcopy(output);wrong['alternatives'][0]['problem_evidence_ids']=['E2']
    with pytest.raises(ValueError):validate(wrong,unrelated)
    agency=deepcopy(output);agency['alternatives'][0]['agency_policy_ids']=['P1']
    with pytest.raises(ValueError):validate(agency,c)
    known=deepcopy(c);known['sources'][0]['agency']='공식 확인 기관'
    assert validate(agency,known)['alternatives'][0]['agency_policy_ids']==['P1']
    second=deepcopy(c);second['need_reviews'].append({**second['need_reviews'][0],'need_id':'N2'})
    with pytest.raises(ValueError,match='unaddressed'):validate(output,second)


def test_single_group_never_uses_other_group_evidence(tmp_path):
    c=context(tmp_path);output=fixture_design(c)
    c['facts'].append({'evidence_id':'E2','target_group':'M/youth','value':.7,'stage':2})
    output['alternatives'][0]['problem_evidence_ids'].append('E2')
    with pytest.raises(ValueError,match='group-specific'):validate(output,c)


# /ship Step 7 pass 1 extension
# Value: protects=only visible policy text or one exact frozen-source reread can ground a completed draft;
# fails_when=hidden quote suffixes pass directly or unknown and repeated information requests escape the bound;
# why_new=the original case covered a successful regional reread but not policy excerpts or request failures;
# seam=none; no_claim=scripted decisions and stored synthetic sources, not actual model judgment or provider acceptance.
def test_generation_uses_raw_frozen_context_and_one_information_reread(service,tmp_path,monkeypatch):
    from backend.policy.pinpoint import generate
    from tests.test_graph import scenario
    import backend.agents.llm as llm
    service.settings.llm_max_calls=4
    run=service.register(scenario('monthly'))
    c=context(tmp_path);scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    c['scope']=scope;original=llm.fake;calls=[]
    def fake(role,payload):
        calls.append(role)
        if role=='policy_alternatives' and not payload.get('requested_information'):
            return {'action':'request_information','alternatives':[],'information_requests':[{'tool':'regional_profile','identifiers':[c['regional_profile']['facts'][0]['fact_id']],'reason':'원천 정의 확인'}]}
        return original(role,payload)
    monkeypatch.setattr(llm,'fake',fake)
    args=(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[])
    body=generate(*args,contexts={c['dong_cd']:c})[0]
    assert body['status']=='draft',body['fallback_reason']
    assert len(body['alternatives'])==3 and all(a['evidence_status']=='concept_only' for a in body['alternatives'])
    assert len(body['evidence']['information_requests'])==1 and len(calls)==2
    assert generate(*args,contexts={c['dong_cd']:c})[0]==body and len(calls)==2
    with pytest.raises(ValueError,match='scope'):generate(service.policy_designer,run.id,run.id,{**scope,'target_groups':['M/youth']},args[4],[],contexts={c['dong_cd']:c})
    for case in ('hidden_quote','policy_reread','unknown_request','repeated_request'):
        current=context(tmp_path/case);current['scope']={**current['scope'],'policy_context_version':'regional-policy-2'}
        full='공식 지원 내용 '+('x'*340)+' / 원문 마지막 신청 조건'
        current['sources'][0]['fields']['support']=full
        current['sources'][0]['evidence']['value']=full
        before=deepcopy(current);captured=[]
        def scripted(role,payload):
            assert role=='policy_alternatives'
            captured.append(deepcopy(payload))
            if case!='hidden_quote' and (not payload.get('requested_information') or case=='repeated_request'):
                return {'action':'request_information','alternatives':[],'information_requests':[{
                    'tool':'policy_detail','identifiers':['unobserved-policy' if case=='unknown_request' else 'P1'],
                    'reason':'정확한 원문 마지막 조건 확인'}]}
            output=original(role,payload)
            for item in output['alternatives']:item['source_elements'][0]['quote']=full
            return output
        monkeypatch.setattr(llm,'fake',scripted)
        current_run=service.register(scenario('monthly'))
        body=generate(service.policy_designer,current_run.id,current_run.id,current['scope'],
            [{'dong_cd':current['dong_cd'],'dong_nm':current['dong_nm']}],[],contexts={current['dong_cd']:current})[0]
        assert current==before
        assert len(captured[0]['sources'][0]['fields']['support'])==300 and full not in str(captured[0]['sources'])
        if case=='policy_reread':
            assert body['status']=='draft' and len(body['alternatives'])==3
            assert len(captured)==2 and captured[1]['requested_information']['items'][0]['fields']['support']==full
            assert body['evidence']['information_requests'][0]['request']['identifiers']==['P1']
            assert body['evidence']['information_requests'][0]['frozen']
            assert all(a['source_elements'][0]['quote']==full for a in body['alternatives'])
        else:
            assert body['status']=='needs_evidence' and body['alternatives']==[]
            assert body['fallback_reason'] and len(captured)==(2 if case=='repeated_request' else 1)


# /ship Step 7 pass 2 extension
# Value: protects=missing substantive policy text yields an empty hold before any model call;
# fails_when=title-only or absent sources generate generic alternatives or reserve a model call;
# why_new=the prior cases covered reuse and missing regional profiles, not missing policy substance;
# seam=none; no_claim=synthetic frozen inputs and a fake-mode ledger, not live policy availability.
def test_existing_sufficient_and_missing_profile_do_not_generate_templates(service,tmp_path):
    from backend.policy.pinpoint import generate
    from tests.test_graph import scenario
    for change in ('reuse','missing'):
        run=service.register(scenario('monthly'));c=context(tmp_path)
        if change=='reuse':c['need_reviews'][0]['decision']='reuse_existing'
        else:c['regional_profile']=None
        scope={**c['scope'],'policy_context_version':'regional-policy-2'}
        body=generate(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
        assert body['alternatives']==[] and body['status']==('reuse_existing' if change=='reuse' else 'needs_evidence')
    for change in ('title_only','no_sources'):
        run=service.register(scenario('monthly'));c=context(tmp_path/change)
        if change=='title_only':c['sources'][0]['fields']={'title':c['sources'][0]['title']}
        else:c['sources']=[]
        before=deepcopy(c);scope={**c['scope'],'policy_context_version':'regional-policy-2'}
        body=generate(service.policy_designer,run.id,run.id,scope,
            [{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
        assert body['status']=='needs_evidence' and body['alternatives']==[]
        assert body['fallback_reason']=='substantive_policy_source_unavailable'
        assert body['generation_mode']=='not_generated' and body['evidence']==before and c==before
        with service.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run.id,)).fetchone()[0]==0


def test_designer_can_explicitly_hold_without_inventing_three(service,tmp_path,monkeypatch):
    from backend.policy.pinpoint import generate
    from tests.test_graph import scenario
    import backend.agents.llm as llm
    run=service.register(scenario('monthly'));c=context(tmp_path);scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    monkeypatch.setattr(llm,'fake',lambda *args:{'action':'needs_evidence','alternatives':[],'information_requests':[],'missing_evidence':['현지 운영 시간 확인']})
    body=generate(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
    assert body['status']=='needs_evidence' and body['alternatives']==[] and body['fallback_reason']=='design_evidence_missing'
    assert body['evidence']['design_questions']==['현지 운영 시간 확인']


# /ship Step 7 pass 1
# Value: protects=one dong aggregates only eligible reviews and consistent frozen snapshots while preserving official agency identity;
# fails_when=conflicting snapshots or reviews merge, unrelated evidence leaks in, or copied agency provenance disappears;
# why_new=the previous tests passed prebuilt contexts directly and bypassed context assembly and dispatch;
# seam=none; no_claim=synthetic proposals and the real fake-mode store, not live source availability or policy quality.
def test_frozen_context_aggregation_preserves_review_and_official_source_identity(service,tmp_path):
    from tests.test_graph import scenario
    c=context(tmp_path/'context');scope={**c['scope'],'policy_context_version':'regional-policy-2'}
    dong={k:c[k] for k in ('dong_cd','dong_nm')}
    review=deepcopy(c['need_reviews'][0]);review['guidance']=[{
        'id':'G1','title':'공식 관계 사업','support':'관계 활동 제공','eligibility':'지역 주민',
        'agency':'공식 확인 기관','application':None,'contact':None}]
    proposal={'task':{'sex':'F','age_group':'youth'},'assessment':{
        'segments':[{'dong_cd':c['dong_cd'],'evidence_id':'E1','stage':2,'value':.5,
                     'index_name':'S1','source_period':'2025-09','source_bands':{'concept':['19–34']}}],
        'regional_context':{c['dong_cd']:c['regional_profile']},'metadata':{'policy_gap_version':'policy-gap-1'}},
        'policy_research':{'need_reviews':[review,{**deepcopy(review),'need_id':'outside','evidence_ids':['outside-evidence']}]}}
    before=deepcopy(proposal)
    frozen=context_for_region(dong,scope,[proposal,deepcopy(proposal)])
    assert proposal==before and len(frozen['need_reviews'])==1
    assert frozen['regional_profile']==c['regional_profile'] and frozen['missing_groups']==[]
    source=next(s for s in frozen['sources'] if s['policy_id']=='G1')
    assert source['fields']=={'support':'관계 활동 제공','eligibility':'지역 주민'}
    assert source.get('agency')=='공식 확인 기관' and source['detail_status']=='frozen_guidance'
    for case in ('missing_hash','different_hash','different_review'):
        changed=deepcopy(proposal)
        if case=='missing_hash':changed['assessment']['regional_context'][c['dong_cd']].pop('input_hash')
        elif case=='different_hash':changed['assessment']['regional_context'][c['dong_cd']]['input_hash']='different-snapshot'
        else:changed['policy_research']['need_reviews'][0]['reason']='서로 다른 검토'
        with pytest.raises(ValueError):context_for_region(dong,scope,[proposal,changed])
    run=service.register(scenario('monthly'))
    output=service.policy_designer.propose(run.id,run.id,scope,[dong],[proposal])[0]
    assert output['proposal_version']=='regional-policy-2' and output['status']=='draft'
    assert len(output['alternatives'])==3 and output['evidence']['regional_profile']==c['regional_profile']
    assert output['response_decisions'][0]['guidance'][0]['agency']=='공식 확인 기관'
    assert all(a['generation_mode']=='fixture' and a['evidence_status']=='concept_only' for a in output['alternatives'])


# /ship Step 7 pass 1
# Value: protects=bounded model input keeps source definitions and reversible references without mutating stored evidence;
# fails_when=any of the 18 regional fields is lost, source copies consume the budget, or essential overflow is silently admitted;
# why_new=existing generation cases did not inspect model metadata, copied outreach, raw input mutation or byte limits;
# seam=none; no_claim=synthetic metadata and encoded-input contracts only, not real model interpretation or policy quality.
def test_model_view_preserves_source_definitions_aliases_and_raw_evidence(service,tmp_path):
    import json
    from backend.agents.llm import PROMPTS
    from backend.policy.alternative_contracts import PinpointDecision
    from backend.policy.pinpoint import model_view,reference_aliases
    c=context(tmp_path);c['facts'][0]['evidence_id']='canonical-problem'
    c['need_reviews'][0].update(need_id='canonical-need',evidence_ids=['canonical-problem'],
        regional_fact_ids=[c['regional_profile']['facts'][0]['fact_id']],
        guidance=[{'support':'stored guidance '*4000}],outreach_draft={'text':'stored announcement '*4000})
    c['sources'][0]['agency']='공식 확인 기관'
    c['sources'][0]['fields']['support']='공식 원문 '+('x'*400)
    before=deepcopy(c);view=model_view(service.policy_designer,c)
    assert c==before
    assert view['facts'][0]['evidence_id']=='E1' and view['need_reviews'][0]['need_id']=='N1'
    assert view['need_reviews'][0]['evidence_ids']==['E1'] and view['need_reviews'][0]['regional_fact_ids']==['R1']
    assert 'guidance' not in view['need_reviews'][0] and 'outreach_draft' not in view['need_reviews'][0]
    shown=view['regional_profile']['areas'][0]['facts'][0];original=c['regional_profile']['facts'][0]
    fields=('metric','value','unit','reference_year','geography_level','geography_code','geography_version',
        'population','age_definition','sex','source','source_table','source_items','source_dimensions','published_at','status','reason')
    assert set(shown)=={'fact_id',*fields} and shown['fact_id']=='R1'
    assert {key:shown[key] for key in fields}=={key:original[key] for key in fields}
    assert reference_aliases(c)['R1']==original['fact_id']
    assert view['sources'][0].get('agency')=='공식 확인 기관'
    assert len(view['sources'][0]['fields']['support'])==300 and len(c['sources'][0]['fields']['support'])>300
    packet={'prompt':(PROMPTS/'policy_alternatives.txt').read_text(),'payload':view,'schema':PinpointDecision.model_json_schema()}
    assert len(json.dumps(packet,ensure_ascii=False).encode())<=service.settings.llm_max_input_bytes
    view['regional_profile']['areas'][0]['facts'][0]['source_items'].append('view-only-change')
    assert c==before
    oversized=deepcopy(c);oversized['need_reviews'][0]['requirements']=['essential requirement '*3000]
    unchanged=deepcopy(oversized)
    with pytest.raises(ValueError,match='pinpoint_context_limit'):model_view(service.policy_designer,oversized)
    assert oversized==unchanged


# /ship Step 7 pass 1
# Value: protects=first-save drafts stay within the requested frozen scope and exhausted call budgets produce evidence holds;
# fails_when=a mismatched supplied context is saved as a valid draft or budget exhaustion is filled with generic alternatives;
# why_new=existing scope rejection covered replay only and did not inspect first-save durable effects or call reservations;
# seam=none; no_claim=synthetic scope and fake-mode call ledger only; no provider spend or real policy-quality assessment.
def test_first_save_rejects_wrong_context_scope_and_budget_preserves_empty_hold(service,tmp_path):
    import json
    from tests.test_graph import scenario
    from backend.policy.pinpoint import generate
    for case in ('analysis_date','dong','target_groups'):
        c=context(tmp_path/case);scope={**c['scope'],'policy_context_version':'regional-policy-2'}
        c['scope']=deepcopy(scope)
        if case=='analysis_date':c['scope']['as_of']='2026-10-23'
        elif case=='dong':c['dong_cd']='11230002'
        else:
            c['target_groups']=['M/youth'];c['facts'][0]['target_group']='M/youth'
            c['need_reviews'][0]['target_group']='M/youth'
        run=service.register(scenario('monthly'));body=None
        try:
            body=generate(service.policy_designer,run.id,run.id,scope,
                [{'dong_cd':'11230001','dong_nm':'생성 지역'}],[],contexts={'11230001':c})
        except ValueError:pass
        assert body is None or (len(body)==1 and body[0]['status']=='needs_evidence' and body[0]['alternatives']==[])
        with service.store.connection() as db:
            saved=db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=?',(run.id,)).fetchall()
        assert all(json.loads(row[0])['alternatives']==[] for row in saved)
    c=context(tmp_path/'budget');scope={**c['scope'],'policy_context_version':'regional-policy-2'};c['scope']=scope
    run=service.register(scenario('monthly'))
    service.settings.llm_max_calls=1
    service.agents.call(run.id,'2025-09-01T09:00:00+09:00','analysis',{'text':'synthetic consumed call'})
    output=generate(service.policy_designer,run.id,run.id,scope,
        [{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
    assert output['status']=='needs_evidence' and output['fallback_reason']=='budget_exhausted'
    assert output['alternatives']==[] and output['generation_mode']=='not_generated'
    with service.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run.id,)).fetchone()[0]==1


# /ship Step 7 pass 2
# Value: protects=legacy alternative calls retain their fixed schema and replay their stored result;
# fails_when=version routing applies the conditional schema to legacy output or replay invokes the provider again;
# why_new=legacy generator fallback can conceal agent schema failures and existing agent coverage omits replay for this role;
# seam=none; no_claim=real fake-mode agent and SQLite contracts, not provider acceptance or model policy quality.
def test_legacy_agent_schema_and_cached_output_remain_compatible(service,monkeypatch):
    import backend.agents.llm as llm
    from backend.policy.alternatives import templates
    from backend.policy.alternative_contracts import Alternatives,PinpointDecision
    from tests.test_graph import scenario
    original=llm.fake
    for version in (None,'adaptation-1'):
        payload={'dong_nm':'기존 지역','target_groups':['F/youth']}
        if version:payload['design_version']=version
        assert llm.schema_for('policy_alternatives',payload) is Alternatives
        expected=templates(payload)
        assert llm.validate_output('policy_alternatives',expected,payload).model_dump()['alternatives']==Alternatives.model_validate(expected).model_dump()['alternatives']
        invalid=deepcopy(expected);invalid['alternatives'][0]['strategy']='free-local-strategy'
        with pytest.raises(ValueError):llm.validate_output('policy_alternatives',invalid,payload)
        hold={'action':'needs_evidence','alternatives':[],'information_requests':[],'missing_evidence':['현장 자료 확인']}
        with pytest.raises(ValueError):llm.validate_output('policy_alternatives',hold,payload)
        assert llm.schema_for('policy_alternatives',{'design_version':'pinpoint-1'}) is PinpointDecision
        assert llm.validate_output('policy_alternatives',hold,{'design_version':'pinpoint-1'}).action=='needs_evidence'
        run=service.register(scenario('monthly'))
        monkeypatch.setattr(llm,'fake',original)
        first=service.agents.call(run.id,'2025-09-01T09:00:00+09:00','policy_alternatives',payload)
        assert isinstance(first,Alternatives) and {a.strategy for a in first.alternatives}=={'outreach','integrated_support','pilot'}
        monkeypatch.setattr(llm,'fake',lambda *args:pytest.fail('cached output must not invoke fake provider'))
        assert service.agents.call(run.id,'2025-09-01T09:00:00+09:00','policy_alternatives',payload)==first
        with service.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run.id,)).fetchone()[0]==1
        assert len([t for t in service.store.traces(run.id) if t['kind']=='llm_result'])==1


# /ship Step 7 pass 2
# Value: protects=unexpected generation errors persist only a sanitized empty evidence hold;
# fails_when=provider exception text leaks into stored sets, call errors or traces, or generic drafts replace failure;
# why_new=the explicit hold and budget tests do not exercise unrelated exceptions at the agent or provider boundary;
# seam=none; no_claim=synthetic exceptions at existing boundaries, not real provider reliability or credential handling.
def test_unexpected_generation_errors_keep_sanitized_empty_holds(service,tmp_path,monkeypatch):
    import json
    import backend.agents.llm as llm
    from backend.policy.pinpoint import generate
    from tests.test_graph import scenario
    original_call=service.agents.call
    for boundary in ('provider','agent'):
        marker='PRIVATE_UNEXPECTED_FAILURE_'+boundary
        def fail(*args):raise RuntimeError(marker)
        monkeypatch.setattr(llm,'fake',fail)
        monkeypatch.setattr(service.agents,'call',original_call if boundary=='provider' else fail)
        run=service.register(scenario('monthly'));c=context(tmp_path/boundary)
        scope={**c['scope'],'policy_context_version':'regional-policy-2'}
        args=(service.policy_designer,run.id,run.id,scope,[{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[])
        body=generate(*args,contexts={c['dong_cd']:c})[0]
        assert body['status']=='needs_evidence' and body['alternatives']==[]
        assert body['fallback_reason']=='design_model_or_validation_unavailable'
        assert body['generation_mode']=='not_generated'
        assert marker not in json.dumps(body,ensure_ascii=False)
        assert marker not in json.dumps(service.store.traces(run.id),ensure_ascii=False)
        with service.store.connection() as db:
            rows=db.execute('SELECT status,body FROM llm_calls WHERE run_id=?',(run.id,)).fetchall()
            saved=db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=?',(run.id,)).fetchone()[0]
        assert len(rows)==(1 if boundary=='provider' else 0)
        assert all(r['status']=='error' and marker not in r['body'] for r in rows)
        assert marker not in saved
        monkeypatch.setattr(service.agents,'call',lambda *args:pytest.fail('stored hold must replay without calls'))
        assert generate(*args,contexts={c['dong_cd']:c})[0]==body


# /ship Step 7 pass 2
# Value: protects=cancelled batches make no new decision or durable alternative set;
# fails_when=an already cancelled batch calls an agent, or cancellation during a decision permits another call or a save;
# why_new=the legacy batch cancellation case never reaches the new conditional generator or its final commit guard;
# seam=none; no_claim=serial cancellation at real decision boundaries, not a concurrency stress test or complete batch workflow.
def test_cancelled_batches_stop_before_calls_and_final_commit(service,tmp_path,monkeypatch):
    import json
    import backend.agents.llm as llm
    from backend.regional_batch import create
    from backend.policy.pinpoint import generate
    from tests.test_regional_batch import request
    original=llm.fake
    for point in ('before_call','before_second_call','before_commit'):
        batch=create(service,request(sex='F',age_group='youth'))
        run_id=batch['children'][0]['run_id'];c=context(tmp_path/point)
        scope={**c['scope'],'policy_context_version':'regional-policy-2'};calls=[]
        def cancel():
            with service.store.connection(write=True) as db:
                stored=json.loads(db.execute('SELECT body FROM regional_batches WHERE id=?',(batch['id'],)).fetchone()[0])
                stored['cancelled']=True
                db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(stored),batch['id']))
        def decide(role,payload):
            calls.append(role);cancel()
            if point=='before_second_call':
                return {'action':'request_information','alternatives':[],'information_requests':[{
                    'tool':'policy_detail','identifiers':['P1'],'reason':'원문 확인'}]}
            return original(role,payload)
        monkeypatch.setattr(llm,'fake',decide)
        if point=='before_call':cancel()
        output=generate(service.policy_designer,batch['id'],run_id,scope,
            [{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})
        assert output==[] and len(calls)==(0 if point=='before_call' else 1)
        with service.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM policy_alternative_sets WHERE owner_id=?',(batch['id'],)).fetchone()[0]==0
            assert db.execute('SELECT COUNT(*) FROM llm_calls WHERE run_id=?',(run_id,)).fetchone()[0]==len(calls)


# /ship Step 7 pass 2
# Value: protects=budget-pruned source IDs cannot authorize a draft while full frozen sources remain stored;
# fails_when=a draft cites a policy omitted from model input and passes against hidden raw sources;
# why_new=excerpt tests kept the same policy ID visible and did not cover removal of an entire source;
# seam=none; no_claim=scripted citations and a byte-bounded fake-mode packet, not model quality or live source completeness.
def test_pruned_policy_cannot_ground_draft_and_raw_sources_survive(service,tmp_path,monkeypatch):
    import json
    import backend.agents.llm as llm
    from backend.policy.alternative_contracts import PinpointDecision
    from backend.policy.pinpoint import generate,model_view
    from tests.test_graph import scenario
    c=context(tmp_path);scope={**c['scope'],'policy_context_version':'regional-policy-2'};c['scope']=scope
    c['sources'].append({'policy_id':'P2','title':'별도 공식 정책','role':'existing_candidate',
        'evidence':{'field':'support','value':'다른 공식 지원 '+('가'*400)},
        'fields':{'support':'다른 공식 지원 '+('가'*400)}})
    before=deepcopy(c);one=deepcopy(c);one['sources']=one['sources'][:1]
    packet={'prompt':(llm.PROMPTS/'policy_alternatives.txt').read_text(),
        'payload':model_view(service.policy_designer,one),'schema':PinpointDecision.model_json_schema()}
    monkeypatch.setattr(service.settings,'llm_max_input_bytes',len(json.dumps(packet,ensure_ascii=False).encode())+64)
    assert [s['policy_id'] for s in model_view(service.policy_designer,c)['sources']]==['P1']
    original=llm.fake
    for citation in ('visible','pruned'):
        captures=[]
        def decide(role,payload):
            captures.append(deepcopy(payload));output=original(role,payload)
            if citation=='pruned':
                for item in output['alternatives']:
                    item['source_policy_ids']=['P2']
                    item['source_elements']=[{'policy_id':'P2','field':'support','quote':'다른 공식 지원'}]
                    item['adaptations'][0]['source_policy_ids']=['P2']
            return output
        monkeypatch.setattr(llm,'fake',decide)
        run=service.register(scenario('monthly'))
        body=generate(service.policy_designer,run.id,run.id,scope,
            [{'dong_cd':c['dong_cd'],'dong_nm':c['dong_nm']}],[],contexts={c['dong_cd']:c})[0]
        assert len(captures)==1 and [s['policy_id'] for s in captures[0]['sources']]==['P1']
        assert body['evidence']['sources']==before['sources'] and c==before
        if citation=='visible':
            assert body['status']=='draft' and len(body['alternatives'])==3
            assert all([s['policy_id'] for s in a['citations']]==['P1'] for a in body['alternatives'])
        else:
            assert body['status']=='needs_evidence' and body['alternatives']==[]
            assert body['fallback_reason']=='design_model_or_validation_unavailable'
