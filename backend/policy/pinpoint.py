"""Conditional region-grounded drafts; failed generation stays an explicit evidence hold."""
import json
from copy import deepcopy
from uuid import uuid5,NAMESPACE_URL
from backend.events import utcnow
from backend.tools.indicators import digest
from backend.policy.alternative_contracts import PinpointAlternatives,PinpointDecision
from backend.policy.alternatives import context_for,research,observed_problem


def context_for_region(dong,scope,proposals):
    context=context_for(dong,scope,proposals);profiles=[];reviews=[]
    evidence_ids={f['evidence_id'] for f in context['facts']}
    for proposal in proposals:
        profile=proposal['assessment'].get('regional_context',{}).get(dong['dong_cd'])
        if profile:profiles.append(profile)
        reviews.extend(r for r in proposal.get('policy_research',{}).get('need_reviews',[]) if set(r['evidence_ids']) and set(r['evidence_ids'])<=evidence_ids)
    if any(not p.get('input_hash') for p in profiles):raise ValueError('regional snapshot missing input hash')
    if len({p['input_hash'] for p in profiles})>1:raise ValueError('conflicting frozen regional snapshots')
    by_id={}
    for review in reviews:
        key=review['need_id']
        if key in by_id and by_id[key]!=review:raise ValueError('conflicting need reviews')
        by_id[key]=review
    reviews=list(by_id.values())
    sources={s['policy_id']:s for s in context['sources']}
    for proposal in proposals:
        for candidate in proposal.get('policy_research',{}).get('candidates',[]):
            policy=candidate.get('policy') or {}
            if policy.get('id') in sources:sources[policy['id']]['agency']=policy.get('agency')
    for review in reviews:
        for policy in review.get('guidance',[]):
            if policy['id'] not in sources:
                sources[policy['id']]={'policy_id':policy['id'],'title':policy['title'],'url':policy.get('url'),'scope':scope['sgg'],'role':'existing_candidate','agency':policy.get('agency'),
                    'evidence':{'field':'support','value':policy.get('support') or policy.get('eligibility') or policy['title']},'checked_at':None,'detail_status':'frozen_guidance',
                    'fields':{k:v for k,v in policy.items() if k in ('support','eligibility','criteria') and isinstance(v,str) and v}}
            elif policy.get('agency'):sources[policy['id']]['agency']=policy['agency']
    context['sources']=list(sources.values())
    context.update(design_version='pinpoint-1',regional_profile=profiles[0] if profiles else None,
                   need_reviews=reviews,missing_groups=sorted(set(scope['target_groups'])-{f['target_group'] for f in context['facts'] if observed_problem(f)}))
    return context


def validate(output,context):
    result=PinpointAlternatives.model_validate(output).model_dump();items=result['alternatives']
    for key in ('strategy','proposed_service','delivery_model'):
        if len({a[key].strip().casefold() for a in items})!=3:raise ValueError('substantively distinct alternatives required')
    if any('target_group' not in f for f in context['facts']):raise ValueError('missing problem target group')
    facts={f['evidence_id']:f for f in context['facts'] if observed_problem(f)}
    region={f['fact_id']:f for f in (context.get('regional_profile') or {}).get('facts',[]) if f['status']=='observed'}
    needs={r['need_id']:r for r in context['need_reviews'] if r['decision'] in ('adapt_existing','new_design_needed')}
    sources={s['policy_id']:s for s in context['sources']}
    covered=set()
    for item in items:
        if len(set(item['need_ids']))!=len(item['need_ids']) or not set(item['need_ids'])<=set(needs):raise ValueError('unverified design need')
        groups={needs[n]['target_group'] for n in item['need_ids']}
        if not set(item['target_groups'])<=groups or not groups<=set(item['target_groups']):raise ValueError('design target differs from selected needs')
        if not set(item['target_groups'])<=set(context['target_groups']):raise ValueError('unrequested group')
        if not item['problem_evidence_ids'] or not set(item['problem_evidence_ids'])<=set(facts):raise ValueError('unobserved problem evidence')
        if {facts[i]['target_group'] for i in item['problem_evidence_ids']}!=groups:raise ValueError('missing group-specific problem evidence')
        need_evidence={i for n in item['need_ids'] for i in needs[n]['evidence_ids']}
        if not set(item['problem_evidence_ids'])<=need_evidence or any(not set(needs[n]['evidence_ids'])&set(item['problem_evidence_ids']) for n in item['need_ids']):raise ValueError('missing need-specific problem evidence')
        if not {link['fact_id'] for link in item['context_links']}<=set(region):raise ValueError('unobserved regional design reference')
        if not item['source_policy_ids'] or not set(item['source_policy_ids'])<=set(sources):raise ValueError('verified policy source required')
        if not set(item['agency_policy_ids'])<=set(item['source_policy_ids']):raise ValueError('unknown operating agency')
        if any(not isinstance(sources[pid].get('agency'),str) or not sources[pid]['agency'].strip() for pid in item['agency_policy_ids']):raise ValueError('unverified agency identity')
        substantive=set()
        for citation in item['source_elements']:
            source=sources.get(citation['policy_id'])
            if citation['policy_id'] not in item['source_policy_ids'] or not source or citation['quote'].replace('\r\n','\n').replace('\r','\n') not in source.get('fields',{}).get(citation['field'],'').replace('\r\n','\n').replace('\r','\n'):raise ValueError('policy quote mismatch')
            if citation['field'] in ('support','eligibility','criteria'):substantive.add(citation['policy_id'])
        if not substantive:raise ValueError('substantive existing-policy comparison required')
        for adaptation in item['adaptations']:
            if not set(adaptation['source_policy_ids'])<=substantive:raise ValueError('adaptation source not quoted')
        if not item['adaptations'] or item['evaluation_design'] is None:raise ValueError('operating difference and evaluation required')
        covered.update(item['need_ids'])
    if covered!=set(needs):raise ValueError('unaddressed design need')
    return result


def fixture_design(context):
    from backend.policy.alternatives import templates
    result=templates(context);needs=[r for r in context['need_reviews'] if r['decision'] in ('adapt_existing','new_design_needed')]
    source=next(s for s in context['sources'] if any(s.get('fields',{}).get(k) for k in ('support','eligibility','criteria')))
    field=next(k for k in ('support','eligibility','criteria') if source['fields'].get(k))
    for item in result['alternatives']:
        item.update(need_ids=[r['need_id'] for r in needs],target_groups=sorted({r['target_group'] for r in needs}),
            problem_evidence_ids=list(dict.fromkeys(i for r in needs for i in r['evidence_ids'])),source_policy_ids=[source['policy_id']],
            delivery_model={'outreach':'방문·신청 접점','integrated_support':'기관 간 의뢰·후속 연락','pilot':'동의 기반 소규모 활동'}[item['strategy']],agency_policy_ids=[],context_links=[{'fact_id':next(f['fact_id'] for f in context['regional_profile'].get('facts',context['regional_profile'].get('areas',[{}])[0].get('facts',[])) if f['status']=='observed'),
                'design_choice':'fake: 제공된 지역 집계 문맥에 맞춘 운영 규모·접점을 담당자와 확인합니다.','verification_needed':'현장 접근 방식과 실제 수요'}],
            source_elements=[{'policy_id':source['policy_id'],'field':field,'quote':source['fields'][field]}],
            adaptations=[{'source_policy_ids':[source['policy_id']],'local_difference':'fake: 지역 집계 문맥과 관측 집단이 다릅니다.','proposed_change':item['proposed_service'],'verification_needed':['현지 대상 조건과 운영 역할']}],
            evaluation_design={'outcome':'참여 유지','baseline_needed':'시행 전 참여 현황','comparison_method':'동의한 비교집단','observation_period':'담당자와 합의','success_criterion_to_agree':'유지율 개선과 부담 감소','stop_criterion_to_agree':'참여 부담 증가'})
        item['strategy']='context-choice-'+str(result['alternatives'].index(item)+1)
    return result


def reference_aliases(context):
    return {**{'E'+str(i+1):f['evidence_id'] for i,f in enumerate(context['facts'])},
        **{'R'+str(i+1):f['fact_id'] for i,f in enumerate(context['regional_profile']['facts'])},
        **{'N'+str(i+1):r['need_id'] for i,r in enumerate(context['need_reviews'])}}


def model_view(designer,context):
    from backend.agents.llm import PROMPTS
    from backend.context.analysis import briefing
    view=deepcopy(context)
    view['regional_profile']=briefing({context['dong_cd']:context['regional_profile']})
    aliases={value:key for key,value in reference_aliases(context).items()}
    for fact in view['facts']:fact['evidence_id']=aliases[fact['evidence_id']]
    for area in view['regional_profile']['areas']:
        for fact in area['facts']:fact['fact_id']=aliases[fact['fact_id']]
        for rate in area['rates']:rate['fact_ids']=[aliases[i] for i in rate['fact_ids']]
    for review in view['need_reviews']:
        review['need_id']=aliases[review['need_id']]
        if not set(review['evidence_ids'])<=set(aliases):raise ValueError('need evidence outside dong')
        review['evidence_ids']=[aliases[i] for i in review['evidence_ids']]
        if not set(review.get('regional_fact_ids',[]))<=set(aliases):raise ValueError('regional need evidence outside dong')
        review['regional_fact_ids']=[aliases[i] for i in review.get('regional_fact_ids',[])]
        if review.get('reason'):review['reason']=review['reason'][:200]
    if view.get('requested_information',{}).get('tool')=='regional_profile':
        for fact in view['requested_information']['items']:fact['fact_id']=aliases[fact['fact_id']]
    view['reference_note']='Use E identifiers for group-specific problem evidence, R for regional facts, N for need IDs exactly. Server restores canonical IDs.'
    view['analyses']=[{**a,'summary':str(a.get('summary',''))[:150]} for a in view['analyses']]
    view.pop('statistics',None);view.pop('matching',None);view.pop('information_requests',None)
    view['need_reviews']=[{k:v for k,v in r.items() if k not in ('guidance','outreach_draft')} for r in view['need_reviews']]
    view['sources']=[{k:s[k] for k in ('policy_id','title','scope','role','agency') if k in s} | {'fields':{k:v[:300] for k,v in s.get('fields',{}).items() if k in ('support','eligibility','criteria')}} for s in view['sources']]
    view['source_view_note']='Exact visible excerpts only; full sources remain stored. No target or feasibility claim beyond supplied fields.'
    overhead=len(json.dumps({'prompt':(PROMPTS/'policy_alternatives.txt').read_text(),'schema':PinpointDecision.model_json_schema()},ensure_ascii=False).encode())
    while len(view['sources'])>1 and len(json.dumps(view,ensure_ascii=False).encode())+overhead+32>designer.settings.llm_max_input_bytes:view['sources'].pop()
    if len(json.dumps(view,ensure_ascii=False).encode())+overhead+32>designer.settings.llm_max_input_bytes:raise ValueError('pinpoint_context_limit')
    return view


def generate(designer,owner,run_id,scope,dongs,proposals,contexts=None):
    results=[]
    for dong in sorted(dongs,key=lambda d:d['dong_cd']):
        with designer.store.connection() as db:
            batch=db.execute('SELECT body FROM regional_batches WHERE id=?',(owner,)).fetchone()
            if batch and json.loads(batch[0])['cancelled']:break
            saved=db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? AND dong_cd=?',(owner,dong['dong_cd'])).fetchone()
        if saved:
            body=json.loads(saved[0])
            if body['scope']!=scope:raise ValueError('owner scope differs from frozen request')
            results.append(body);continue
        context=deepcopy(contexts[dong['dong_cd']]) if contexts else context_for_region(dong,scope,proposals)
        if context['dong_cd']!=dong['dong_cd'] or context['target_groups']!=scope['target_groups'] or any(context['scope'].get(k)!=scope.get(k) for k in ('sgg','ym','as_of','target_groups')):raise ValueError('frozen_context_scope_mismatch')
        design_needs=[r for r in context['need_reviews'] if r['decision'] in ('adapt_existing','new_design_needed')]
        status='needs_evidence';reason='need_review_incomplete';output={'alternatives':[]};mode='not_generated'
        if context['need_reviews'] and not design_needs:
            status='reuse_existing' if all(r['decision']=='reuse_existing' for r in context['need_reviews']) else 'needs_evidence'
            reason='existing_policy_sufficient' if status=='reuse_existing' else 'material_information_missing'
        elif design_needs:
            try:
                if not any(f['status']=='observed' for f in (context.get('regional_profile') or {}).get('facts',[])):raise ValueError('regional_context_unavailable')
                if not contexts:context=research(designer,owner,run_id,context)
                if not any(any(s.get('fields',{}).get(k) for k in ('support','eligibility','criteria')) for s in context['sources']):raise ValueError('substantive_policy_source_unavailable')
                view=model_view(designer,context)
                for attempt in range(2):
                    with designer.store.connection() as db:
                        batch=db.execute('SELECT body FROM regional_batches WHERE id=?',(owner,)).fetchone()
                        if batch and json.loads(batch[0])['cancelled']:raise ValueError('cancelled')
                    decision=designer.agents.call(run_id,scope['ym']+'-01T09:00:00+09:00','policy_alternatives',view).model_dump()
                    aliases=reference_aliases(context)
                    for item in decision['alternatives']:
                        item['problem_evidence_ids']=[aliases.get(i,i) for i in item['problem_evidence_ids']]
                        item['need_ids']=[aliases.get(i,i) for i in item['need_ids']]
                        for link in item['context_links']:link['fact_id']=aliases.get(link['fact_id'],link['fact_id'])
                    if decision['action']=='needs_evidence':
                        if decision['alternatives'] or decision['information_requests'] or not decision['missing_evidence']:raise ValueError('invalid design evidence hold')
                        context['design_questions']=decision['missing_evidence']
                        raise ValueError('design_evidence_missing')
                    if decision['action']=='draft':
                        if decision['information_requests']:raise ValueError('draft includes information request')
                        visible_sources={s['policy_id']:s for s in view['sources']}
                        if view.get('requested_information',{}).get('tool')=='policy_detail':visible_sources.update({s['policy_id']:s for s in view['requested_information']['items']})
                        output=validate({'alternatives':decision['alternatives']},{**context,'sources':list(visible_sources.values())})
                        break
                    if attempt or decision['alternatives'] or len(decision['information_requests'])!=1:raise ValueError('information_request_limit')
                    query=decision['information_requests'][0]
                    query['identifiers']=[aliases.get(i,i) for i in query['identifiers']]
                    collection=context['regional_profile']['facts'] if query['tool']=='regional_profile' else context['sources']
                    field='fact_id' if query['tool']=='regional_profile' else 'policy_id'
                    selected=[r for r in collection if r[field] in query['identifiers']]
                    if {r[field] for r in selected}!=set(query['identifiers']):raise ValueError('unobserved_information_request')
                    # Re-read the frozen source: current provider changes cannot replace this run's evidence.
                    context['requested_information']={'tool':query['tool'],'frozen':True,'items':selected}
                    context['information_requests']=[{'request':query,'source_hash':digest(selected),'frozen':True}]
                    designer.store.append_trace(run_id,utcnow().isoformat(),'tool_result',context['requested_information'],'policy_design')
                    view=model_view(designer,context)
                status='draft';reason=None;mode='llm' if designer.settings.llm_mode=='live' else 'fixture'
            except Exception as exc:
                code=str(exc) if isinstance(exc,ValueError) else ''
                reason={'LLM call or cost budget exceeded':'budget_exhausted','LLM input budget exceeded':'context_input_limit','pinpoint_context_limit':'context_input_limit'}.get(code,code if code in ('regional_context_unavailable','substantive_policy_source_unavailable','information_request_limit','design_evidence_missing','cancelled') else 'design_model_or_validation_unavailable')
        for index,item in enumerate(output['alternatives']):
            item.update(id=str(uuid5(NAMESPACE_URL,owner+':'+dong['dong_cd']+':pinpoint:'+str(index))),generation_mode=mode,
                evidence_status='concept_only' if mode=='fixture' else 'supported',status='draft',review_status='pending',allocation_performed=False,
                citations=[s for s in context['sources'] if s['policy_id'] in item['source_policy_ids']],
                agency_references=[{'policy_id':s['policy_id'],'agency':s['agency'],'role':'registered_publisher','local_participation_confirmed':False} for s in context['sources'] if s['policy_id'] in item['agency_policy_ids']],
                design_checks={'status':'structured_draft','gaps':[],'effectiveness_verified':False},
                claim_limits={'local_need':'hypothesis_only','feasibility':'not_evaluated','effectiveness':'not_evaluated','field_gap':'not_evaluated',
                    'operating_roles':'proposed_only','venue':'not_confirmed','budget':'not_approved','capacity':'not_confirmed'})
        body={**output,**dong,'owner_id':owner,'scope':scope,'status':status,'fallback_reason':reason,'generation_mode':mode,
            'input_version':digest(context),'created_at':utcnow().isoformat(),'review_revision':0,'human_review_required':True,
            'data_mode':designer.settings.data_mode,'llm_mode':designer.settings.llm_mode,'allocation_performed':False,'budget_approved':False,'evidence':context,
            'response_decisions':context['need_reviews'],'missing_groups':context['missing_groups'],'proposal_version':'regional-policy-2'}
        body['version']=digest(body)
        with designer.store.connection(write=True) as db:
            batch=db.execute('SELECT body FROM regional_batches WHERE id=?',(owner,)).fetchone()
            if batch and json.loads(batch[0])['cancelled']:break
            db.execute('INSERT OR IGNORE INTO policy_alternative_sets VALUES (?,?,?)',(owner,dong['dong_cd'],json.dumps(body,ensure_ascii=False)))
            body=json.loads(db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? AND dong_cd=?',(owner,dong['dong_cd'])).fetchone()[0])
        if body['scope']!=scope:raise ValueError('owner scope differs from frozen request')
        results.append(body)
    return results
