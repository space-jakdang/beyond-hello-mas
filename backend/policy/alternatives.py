"""Always-three policy drafts, with explicit template fallback and durable evidence."""
import json
import time
from copy import deepcopy
from uuid import uuid5, NAMESPACE_URL
from backend.events import utcnow
from backend.tools.indicators import digest
from backend.policy.alternative_contracts import Alternatives

STRATEGIES={
 'outreach':('접근 경로 개선','지역 접점과 안내 채널을 점검하고, 신청·연결을 돕는 접근성 개선안을 검토합니다.',['기존 안내·의뢰 경로 확인','참여 장벽 확인','작은 범위에서 안내 방식 시범 적용']),
 'integrated_support':('지속 연결 지원','기관 간 의뢰와 후속 연락을 연결하는 지속 지원 운영안을 검토합니다.',['연결 가능한 기관 확인','동의 기반 의뢰 절차 설계','연결 이후 이탈·불편 확인']),
 'pilot':('지역 맞춤 시범사업','관측된 필요 가설을 현장과 확인하고, 대상별 참여 방식을 조정하는 작은 시범사업을 검토합니다.',['대상 집단의 필요 확인','실행 가능한 운영 방식 합의','부담과 참여 유지 관찰'])}


def templates(context):
    return {'alternatives':[{'strategy':key,'title':context['dong_nm']+' '+title,'target_groups':context['target_groups'],
        'problem_evidence_ids':[],'source_policy_ids':[],'rationale':'자료를 보완하며 검토하는 운영 구상입니다. 현지 효과·실현 가능성은 확인되지 않았습니다.',
        'proposed_service':service,'operating_steps':steps,'required_roles':['정책 담당자','현지 협력기관'],
        'budget_questions':['운영 인력과 비용 항목 확인','예산 근거·수용량 확인'],
        'equity_risks':['접근성 격차·낙인·참여 부담 확인'],
        'evaluation_plan':'시행 전 기준선과 비교 방법을 합의하고 참여·유지·부담을 관찰합니다. 성공·중단 기준은 담당자가 확정합니다.',
        'missing_evidence':['대상별 현장 필요','실제 이용량·수용량','시행 근거·예산']} for key,(title,service,steps) in STRATEGIES.items()]}


def validate(output,context):
    result=Alternatives.model_validate(output).model_dump()
    items=result['alternatives']
    if {a['strategy'] for a in items}!=set(STRATEGIES):raise ValueError('three distinct strategies required')
    if len({a['proposed_service'].strip() for a in items})!=3:raise ValueError('duplicate alternatives')
    evidence={r['evidence_id']:r for r in context['facts']};sources={r['policy_id']:r for r in context['sources']}
    for item in items:
        if not set(item['target_groups'])<=set(context['target_groups']):raise ValueError('unrequested target')
        if not set(item['problem_evidence_ids'])<=set(evidence):raise ValueError('unknown regional evidence')
        if not set(item['source_policy_ids'])<=set(sources):raise ValueError('unknown policy citation')
        if len(set(item['target_groups']))!=len(item['target_groups']):raise ValueError('duplicate target')
        for identifier in item['problem_evidence_ids']:
            fact=evidence[identifier]
            if fact['target_group'] not in item['target_groups'] or fact['value'] is None or fact['stage'] is None:
                raise ValueError('unobserved or unrelated evidence')
    return result


def context_for(dong,scope,proposals):
    facts=[];sources={};analyses=[];statistics=[];matching=[]
    groups=scope['target_groups']
    for proposal in proposals:
        group=proposal['task']['sex']+'/'+proposal['task']['age_group']
        selected=[r for r in proposal['assessment']['segments'] if r['dong_cd']==dong['dong_cd']]
        ids={r['evidence_id'] for r in selected}
        facts.extend({'evidence_id':r['evidence_id'],'target_group':group,'stage':r['stage'],'index_name':r['index_name'],
                      'value':r['value'],'source_period':r['source_period'],'flags':r.get('flags',[])} for r in selected)
        analyses.append({'target_group':group,'summary':(proposal.get('workflow',{}).get('analysis') or {}).get('summary','분석 미완료')})
        stats=proposal.get('workflow',{}).get('statistics',{})
        statistics.extend(i for i in stats.get('summary',{}).get('insights',{}).get('items',[]) if i['evidence_id'] in ids)
        matching.extend({'evidence_id':a['evidence_id'],'needs':a.get('needs',[]),'uncovered_needs':a.get('uncovered_needs',[]),
                         'selected_resource_ids':[r['id'] for r in a.get('recommendations',[])]} for a in proposal.get('assignments',[]) if a['evidence_id'] in ids)
        for c in (proposal.get('policy_research') or {}).get('candidates',[]):
            policy=c['policy'];pid=policy['id']
            # Exact validated quote is attached by the server, not rewritten by the model.
            sources[pid]={'policy_id':pid,'title':policy['title'],'url':policy.get('url'),'scope':policy['scope'],
                          'evidence':c['evidence'],'checked_at':c.get('checked_at') or c.get('cached_at'),
                          'detail_status':c['detail_status'],'role':'existing_candidate'}
    return {**dong,'scope':scope,'target_groups':groups,'facts':facts,'analyses':analyses,'statistics':statistics,'matching':matching,
            'sources':list(sources.values()),'limits':['예산·정원·효과는 미확인','정책 부재를 증명한 것이 아닙니다.']}


def research(designer,owner_id,run_id,context):
    if context['sources']:
        context['source_search_status']='existing_candidates'
        return context
    needs={n for row in context['matching'] for n in row['needs']}
    query=next((word for key,word in [('economic','경제'),('housing','주거'),('employment','일자리'),('health','건강')] if key in needs),'관계')
    args={'local_scope':{'11230':'gangnam','32010':'chuncheon'}[context['scope']['sgg']],
          'query':query,'target_group':', '.join(context['target_groups'])}
    cache_key=digest(args)
    with designer.store.connection() as db:
        row=db.execute('SELECT body FROM policy_alternative_research WHERE owner_id=? AND cache_key=?',(owner_id,cache_key)).fetchone()
    if row:result=json.loads(row[0])
    else:
        try:result=designer.policy_agent.call_tool('policy_analogues',args)
        except Exception as exc:result={'status':'unavailable','error_type':type(exc).__name__}
        with designer.store.connection(write=True) as db:
            db.execute('INSERT OR IGNORE INTO policy_alternative_research VALUES (?,?,?)',(owner_id,cache_key,json.dumps(result,ensure_ascii=False)))
            result=json.loads(db.execute('SELECT body FROM policy_alternative_research WHERE owner_id=? AND cache_key=?',(owner_id,cache_key)).fetchone()[0])
            designer.store._trace(db,run_id,utcnow().isoformat(),'tool_result',{'tool':'policy_analogues','arguments':args,'result':result},'policy_design')
    context['source_search_status']=result.get('status','unavailable')
    for analogue in result.get('analogues',[])[:5]:
        source=analogue.get('source',{})
        if source.get('policy_id') and source.get('fields',{}).get('title'):
            context['sources'].append({'policy_id':source['policy_id'],'title':source['title'],'url':source.get('source_url'),
             'scope':source.get('scope'),'checked_at':source.get('checked_at'),'detail_status':'reference_only',
             'evidence':{'field':'title','value':source['fields']['title']},'role':'analogue_not_local_eligibility'})
    return context


def model_context(context):
    view=deepcopy(context)
    view['analyses']=[{**a,'summary':str(a.get('summary',''))[:300]} for a in context['analyses']]
    view['statistics']=[{k:v for k,v in row.items() if k in ('evidence_id','comparison','measured_need_signals')} for row in context['statistics']]
    view['sources']=[{k:v for k,v in source.items() if k!='url'} | {'evidence':{**source['evidence'],'value':source['evidence']['value'][:400]}} for source in context['sources']]
    view['source_view_note']='Policy quote previews may be truncated. Cite IDs; server attaches the original quote.'
    return view


def generate(designer,owner_id,run_id,scope,dongs,proposals):
    results=[]
    for dong in sorted(dongs,key=lambda d:d['dong_cd']):
        with designer.store.connection() as db:
            batch=db.execute('SELECT body FROM regional_batches WHERE id=?',(owner_id,)).fetchone()
            if batch and json.loads(batch[0])['cancelled']:break
            saved=db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? AND dong_cd=?',(owner_id,dong['dong_cd'])).fetchone()
        if saved:
            results.append(json.loads(saved[0]));continue
        context=context_for(dong,scope,proposals)
        if any(r['value'] is not None for r in context['facts']):context=research(designer,owner_id,run_id,context)
        reason=None;mode='llm' if designer.settings.llm_mode=='live' else 'fixture';item_modes={}
        if not any(r['value'] is not None and r['stage'] is not None for r in context['facts']):
            output=templates(context);mode='template_fallback';reason='regional_evidence_unavailable'
        else:
            try:
                candidate=designer.agents.call(run_id,scope['ym']+'-01T09:00:00+09:00','policy_alternatives',model_context(context)).model_dump()
                output=templates(context);used=set()
                for i,item in enumerate(output['alternatives']):
                    options=[a for a in candidate['alternatives'] if a['strategy']==item['strategy']]
                    try:
                        if len(options)!=1 or options[0]['proposed_service'].strip() in used:raise ValueError('duplicate strategy or service')
                        trial=templates(context);trial['alternatives'][i]=options[0];validate(trial,context)
                        output['alternatives'][i]=options[0];used.add(options[0]['proposed_service'].strip())
                        item_modes[item['strategy']]=mode
                    except ValueError:
                        item_modes[item['strategy']]='template_fallback';reason='invalid_alternative_evidence'
                if set(item_modes.values())=={'template_fallback'}:mode='template_fallback'
                elif 'template_fallback' in item_modes.values():mode='mixed'
            except Exception as exc:
                output=templates(context);mode='template_fallback';reason=type(exc).__name__
        output=validate(output,context)
        for item in output['alternatives']:
            covered={r['target_group'] for r in context['facts'] if r['evidence_id'] in item['problem_evidence_ids']}
            missing=set(item['target_groups'])-covered
            item['missing_evidence']=list(dict.fromkeys(item['missing_evidence']+['지역 관측 근거 없음: '+g for g in sorted(missing)]))
            item.update(id=str(uuid5(NAMESPACE_URL,owner_id+':'+dong['dong_cd']+':'+item['strategy'])),
                        generation_mode=item_modes.get(item['strategy'],mode),evidence_status='supported' if not missing and item['source_policy_ids'] else 'partial' if covered else 'concept_only',
                        status='needs_evidence',review_status='pending',allocation_performed=False)
            item['citations']=[s for s in context['sources'] if s['policy_id'] in item['source_policy_ids']]
        body={**output,'owner_id':owner_id,**dong,'scope':scope,'input_version':digest(context),'generation_mode':mode,
              'fallback_reason':reason,'created_at':utcnow().isoformat(),'review_revision':0,'human_review_required':True,
              'data_mode':designer.settings.data_mode,'llm_mode':designer.settings.llm_mode,'budget_approved':False,'allocation_performed':False,'evidence':context}
        body['version']=digest(body)
        with designer.store.connection(write=True) as db:
            db.execute('INSERT OR IGNORE INTO policy_alternative_sets VALUES (?,?,?)',(owner_id,dong['dong_cd'],json.dumps(body,ensure_ascii=False)))
            stored=json.loads(db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? AND dong_cd=?',(owner_id,dong['dong_cd'])).fetchone()[0])
        results.append(stored)
    return results


def failed_run(service,run_id,scenario):
    payload=scenario['payload']
    if payload.get('policy_proposal_version')!='three-1':return
    from backend.tools.segments_v3 import load_segments
    task=payload['task'];rows,_=load_segments(service.settings)
    known={r.dong_cd:r.dong_nm for r in rows if r.sgg==task['sgg'] and (not task.get('dong_cd') or r.dong_cd==task['dong_cd'])}
    scope={'sgg':task['sgg'],'ym':task['ym'],'as_of':task['as_of'],'target_groups':[task['sex']+'/'+task['age_group']],'synthetic_future':bool(task.get('future_id'))}
    service.policy_designer.propose(run_id,run_id,scope,[{'dong_cd':k,'dong_nm':v} for k,v in known.items()],[])


def complete_batch(service,body):
    from backend.app.contracts import Scenario
    from backend.regional_batch import read
    latest=read(service,body['id'])
    if latest['cancelled'] or latest.get('policy_proposals'):return
    owner=body['id'];identifier=str(uuid5(NAMESPACE_URL,'policy-batch:'+owner))
    scenario=Scenario(id='regional-policy-design-batch',type='monthly',sim_time=utcnow().isoformat(),payload={})
    run=service.new_run(scenario,identifier)
    with service.store.connection(write=True) as db:
        if not db.execute('SELECT 1 FROM runs WHERE id=?',(identifier,)).fetchone():
            db.execute('INSERT INTO runs VALUES (?,?)',(identifier,run.model_dump_json()))
            db.execute('INSERT INTO run_clocks VALUES (?,?,?)',(identifier,service.store.clock_id,time.monotonic()))
            # Share parent's monetary budget; this run is not one of the analysis children.
            db.execute('INSERT INTO regional_batch_children VALUES (?,?,?)',(identifier,owner,'{}'))
    proposals=[]
    for child in body['children']:
        if child['run_id']:
            try:proposals.append(service.approval(child['run_id'])['proposal'])
            except KeyError:pass
    task=body['task'];scope={'sgg':task['sgg'],'ym':task['ym'],'as_of':task['as_of'],
                            'target_groups':[c['sex']+'/'+c['age_group'] for c in body['children']],'synthetic_future':False}
    sets=service.policy_designer.propose(owner,identifier,scope,body['dongs'],proposals)
    with service.store.connection(write=True) as db:
        latest=json.loads(db.execute('SELECT body FROM regional_batches WHERE id=?',(owner,)).fetchone()[0])
        service.update_run(db,identifier,status='cancelled' if latest['cancelled'] else 'completed',ended_at=utcnow())
        if latest['cancelled']:return
        latest['policy_proposals']={'owner_id':owner,'dong_count':len(sets),'fallback_count':sum(any(a['generation_mode']=='template_fallback' for a in s['alternatives']) for s in sets),'status':'completed_with_fallback' if any(a['generation_mode']=='template_fallback' for s in sets for a in s['alternatives']) else 'completed'}
        db.execute('UPDATE regional_batches SET body=? WHERE id=?',(json.dumps(latest,ensure_ascii=False),owner))


def router(store):
    from fastapi import APIRouter,HTTPException
    from uuid import UUID
    result=APIRouter(prefix='/policy-proposals')
    @result.get('/{owner_id}')
    def get(owner_id:UUID):
        with store.connection() as db:
            rows=db.execute('SELECT body FROM policy_alternative_sets WHERE owner_id=? ORDER BY dong_cd',(str(owner_id),)).fetchall()
        if not rows:raise HTTPException(404,'정책 대안을 아직 생성하지 않았습니다.')
        return {'owner_id':str(owner_id),'sets':[json.loads(r[0]) for r in rows]}
    return result
