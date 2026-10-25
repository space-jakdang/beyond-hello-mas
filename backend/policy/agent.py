"""Supervisor-scoped ReAct worker. Tool observations, not private reasoning, are persisted."""
from backend.tools.indicators import digest
import asyncio
import json
import os
import sys
import time
from typing import Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.config import ROOT
from backend.policy.service import SCOPES, Scope, LIMITATION
from backend.policy.research_contracts import ResearchNeed,NeedReview,MaterialPolicyError,evidence_hold,regional_briefing,latest_details,validate_reviews,catalog_policy,visible_policy_fields


class PolicyTask(BaseModel):
    model_config=ConfigDict(extra='forbid')
    goal:str=Field(min_length=1,max_length=1000)
    scopes:list[Scope]=Field(default_factory=lambda:SCOPES.copy(),min_length=1,max_length=5)
    query:str=Field(default='',max_length=200)
    max_steps:int=Field(default=6,ge=1,le=10)
    research_version:Literal['regional-research-1','regional-research-2'] | None = None
    needs:list[ResearchNeed]=Field(default_factory=list,max_length=50)
    regional_profiles:list[dict]=Field(default_factory=list,max_length=47)
    statistical_notes:list[dict]=Field(default_factory=list,max_length=5)
    existing_resources:list[dict]=Field(default_factory=list,max_length=15)

    @model_validator(mode='after')
    def distinct_needs(self):
        if len({n.need_id for n in self.needs})!=len(self.needs):raise ValueError('duplicate research need')
        return self


class PolicyEvidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    policy_id:str
    field:Literal['title','eligibility','criteria','support','deadline','application','contact','agency']
    value:str
    explanation:str


class PolicyDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['policy_coverage','policy_refresh','policy_search','policy_detail','policy_details','policy_field','finish']
    query:str
    page:int
    policy_id:str | None
    policy_ids:list[str]=Field(default_factory=list,max_length=5)
    detail_field:Literal['support','eligibility','criteria','application','deadline','contact','agency'] | None = None
    recommendations:list[PolicyEvidence]=Field(max_length=5)
    reason:str
    need_reviews:list[NeedReview]=Field(default_factory=list,max_length=50)


def fake_decision(payload):
    observations=payload['observations']
    result={'action':'policy_refresh','query':'','page':1,'policy_id':None,'recommendations':[],
            'reason':'fake: deterministic protocol fixture, not model reasoning'}
    if not observations and payload['task'].get('research_version') and payload['task'].get('existing_resources'):
        result['action']='finish'
        result['need_reviews']=[]
        for need in payload['task']['needs']:
            resources=[r for r in payload['task']['existing_resources'] if need['need'] in r['needs']]
            from backend.context.analysis import observed_ids
            facts=sorted(observed_ids(payload['task']['regional_profiles']))
            adapt=bool(resources and need.get('verified_gaps') and facts)
            result['need_reviews'].append({'need_id':need['need_id'],'decision':'adapt_existing' if adapt else 'needs_evidence' if need.get('verified_gaps') else 'reuse_existing' if resources else 'needs_evidence',
                'policy_ids':['catalog:'+r['id'] for r in resources[:3]],'citations':[{'policy_id':'catalog:'+r['id'],'field':'support','quote':r['evidence']} for r in resources[:3]],
                'regional_fact_ids':facts[:1] if adapt else [],'unmet_requirements':need['verified_gaps'] if adapt else [],'reason':'fake: 필터를 통과한 기존 자원의 제공 내용과 관측 연령 범위를 검토합니다.',
                'missing_evidence':['개인 자격·실제 신청 경로·정원과 운영 상황 확인'],
                'proposed_channel':'담당자 검토 후 공식 안내문 게시 제안'})
        return result
    if not observations:return result
    last=observations[-1]['result'];tool=observations[-1]['action']['action']
    if tool=='policy_refresh' and last.get('status')=='cached':
        result.update(action='policy_search',query=payload['task']['query'])
    elif tool=='policy_search' and last.get('items'):
        result.update(action='policy_details',policy_ids=[p['id'] for p in last['items'][:5]]) if len(last['items'])>1 else result.update(action='policy_detail',policy_id=last['items'][0]['id'])
    else:
        result['action']='finish'
        if tool=='policy_details':
            result['recommendations']=[{'policy_id':r['policy']['id'],'field':'title','value':r['policy']['title'],
                'explanation':'fake: 조회된 정책 후보이며 현장 적격성은 미확인입니다.'} for r in last.get('items',[]) if r.get('policy')]
        if tool=='policy_detail' and last.get('policy'):
            p=last['policy'];result['recommendations']=[{'policy_id':p['id'],'field':'title','value':p['title'],
                'explanation':'fake: 조회된 정책 후보입니다. 적격성은 담당자가 확인해야 합니다.'}]
    if result['action']=='finish' and payload['task'].get('research_version'):
        result['need_reviews']=[{'need_id':n['need_id'],'decision':'needs_evidence','policy_ids':[], 'citations':[],
            'regional_fact_ids':[],'unmet_requirements':[],'reason':'fake: 필요별 적합성과 운영 요건을 추가 확인합니다.',
            'missing_evidence':['공식 지원 내용과 요건의 대조']} for n in payload['task']['needs']]
    return result


def compact(value):
    # The full observation stays in SQLite; bounded copies alone enter the model context.
    if isinstance(value,str):return value[:800]
    if isinstance(value,list):return [compact(x) for x in value[:5]]
    if isinstance(value,dict):return {k:compact(v) for k,v in value.items()}
    return value


class PolicyAgent:
    def __init__(self,store,settings,agents):
        self.store,self.settings,self.agents=store,settings,agents
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS policy_steps (run_id TEXT NOT NULL REFERENCES runs(id), step INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(run_id,step))')
            db.execute('CREATE TABLE IF NOT EXISTS policy_alternative_research (owner_id TEXT NOT NULL,cache_key TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(owner_id,cache_key))')

    def frozen_tool(self,owner,tool,args):
        def read(key):
            with self.store.connection() as db:
                row=db.execute('SELECT body FROM policy_alternative_research WHERE owner_id=? AND cache_key=?',(owner,key)).fetchone()
            return json.loads(row[0]) if row else None
        def save(key,result):
            with self.store.connection(write=True) as db:
                db.execute('INSERT OR IGNORE INTO policy_alternative_research VALUES (?,?,?)',(owner,key,json.dumps(result,ensure_ascii=False)))
                return json.loads(db.execute('SELECT body FROM policy_alternative_research WHERE owner_id=? AND cache_key=?',(owner,key)).fetchone()[0])
        if tool in ('policy_detail','policy_details'):
            ids=args['policy_ids'] if tool=='policy_details' else [args['policy_id']]
            identities={pid:digest(['regional-research-2','policy_detail',pid]) for pid in ids}
            known={pid:read(key) for pid,key in identities.items()};missing=[pid for pid in ids if known[pid] is None]
            result={}
            if missing:
                result=self.call_tool(tool,{'policy_ids':missing} if tool=='policy_details' else {'policy_id':missing[0]})
                rows=result.get('items',[]) if tool=='policy_details' else [result]
                for pid in missing:
                    detail=next((r for r in rows if (r.get('policy') or {}).get('id')==pid),None)
                    if detail is None:detail={'status':result.get('status','not_found'),'policy':None,'rejected_result':result}
                    known[pid]=save(identities[pid],detail)
            return {**result,'status':'complete','items':[known[pid] for pid in ids]} if tool=='policy_details' else known[ids[0]]
        fingerprint=digest(['regional-research-2',tool,args]);cached=read(fingerprint)
        return cached if cached is not None else save(fingerprint,self.call_tool(tool,args))

    async def remote(self,tool,args):
        env={'DATA_MODE':self.settings.data_mode,'LLM_MODE':'fake',
             'INPUT_ROOT':str(self.settings.data_dir.parent),'RUNTIME_STORAGE_ROOT':str(self.settings.runtime_root),
             'GOV24_SERVICE_KEY':self.settings.gov24_service_key.get_secret_value() if self.settings.gov24_service_key else '',
             'POLICY_TIMEOUT_SECONDS':str(self.settings.policy_timeout_seconds),'POLICY_MAX_PAGES':str(self.settings.policy_max_pages),
             'EVALUATION_ID':str(self.settings.evaluation_id) if self.settings.evaluation_id else ''}
        parameters=StdioServerParameters(command=sys.executable,args=['-m','backend.policy.server'],cwd=str(ROOT),env=env)
        with open(os.devnull,'w') as log:
            async with stdio_client(parameters,errlog=log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    response=await session.call_tool(tool,args)
                    if response.is_error or not isinstance(response.structured_content,dict):raise ValueError('invalid_tool_result')
                    return response.structured_content

    def call_tool(self,tool,args):
        async def invoke():
            timeout=60+self.settings.policy_timeout_seconds+5 if tool=='policy_refresh' else (10 if tool in ('policy_details','policy_analogues') else 2)*self.settings.policy_timeout_seconds+10
            return await asyncio.wait_for(self.remote(tool,args),timeout)
        try:return asyncio.run(invoke())
        except Exception as exc:return {'status':'error','error':type(exc).__name__}

    def model_payload(self,task,observations,remaining):
        # Full observations stay in policy_steps; only this model view is reduced.
        view=[]
        for original in observations:
            entry=compact(original)
            action=entry['action']['action']
            if action=='policy_search':
                entry['result']['items']=[{k:p[k] for k in ('id','title','scope','agency') if k in p} |
                    {'summary_preview':str(p.get('summary',''))[:160]} for p in original['result'].get('items',[])[:5]]
            if action=='policy_detail' and original['result'].get('policy'):
                p=original['result']['policy']
                entry['result']['policy']={k:p[k] for k in ('id','title','scope','agency') if k in p} | {
                    'support_preview':str(p.get('support',''))[:160],
                    'eligibility_preview':str(p.get('eligibility',''))[:160]}
            if action=='policy_details':
                entry['result']['items']=[{k:r.get(k) for k in ('status','checked_at','cached_at')} | {
                    'policy':{k:r['policy'][k] for k in ('id','title','scope','agency') if k in r['policy']} | {
                        'support_preview':str(r['policy'].get('support',''))[:160],
                        'eligibility_preview':str(r['policy'].get('eligibility',''))[:160]}
                    if r.get('policy') else None} for r in original['result'].get('items',[])[:5]]
            view.append(entry)
        task_view=task.model_dump()
        if task.research_version:
            from backend.context.analysis import model_briefing
            task_view['regional_profiles']=model_briefing(regional_briefing(task.regional_profiles))
            details=latest_details(observations)
            for entry,source_observation in zip(view,observations):
                rows=entry['result'].get('items',[]) if entry['action']['action']=='policy_details' else [entry['result']] if entry['action']['action']=='policy_detail' else []
                for row in rows:
                    if row.get('policy'):
                        detail=details[row['policy']['id']]
                        original=detail.get('policy')
                        row['status']=detail['status']
                        if not original:
                            row.update(policy=None,conditions=None)
                            continue
                        row['policy'].update({k:original[k] for k in ('id','title','scope') if k in original})
                        row['conditions']=compact(detail.get('conditions'))
                        row['policy']['field_view']='excerpts; request policy_field for the complete frozen field'
                        row['policy'].update({k:str(original.get(k,'') or '')[:200] for k in ('support','eligibility','criteria','application','deadline','contact','agency')})
                if entry['action']['action']=='policy_field':
                    raw=source_observation['result']
                    policy=(details.get(raw['policy_id']) or {}).get('policy')
                    entry['result']=dict(raw) if policy and raw.get('source_hash')==digest(policy) else {**raw,'status':'superseded','value':None}
        payload={'task':task_view,'observations':view,'steps_remaining':remaining,
                 'tools':['policy_coverage','policy_refresh','policy_search','policy_detail','policy_details','finish']+(['policy_field'] if task.research_version else [])}
        prompt=(ROOT/'backend/prompts/policy_decision.txt').read_text()
        def fits():
            return len(json.dumps({'prompt':prompt,'payload':payload,'schema':PolicyDecision.model_json_schema()},ensure_ascii=False).encode())<=self.settings.llm_max_input_bytes
        while not fits():
            search=next((o for o in view if o['action']['action']=='policy_search' and o['result'].get('items')),None)
            if search:
                search['result']['items'].pop(0)
                search['result']['model_items_omitted']=True
            elif len(view)>1:
                index=next((i for i,o in enumerate(view) if o['action']['action'] not in ('policy_detail','policy_details','policy_field')),None)
                if index is None:raise ValueError('policy_context_limit')
                view.pop(index)
            else:
                raise ValueError('policy_context_limit')
        return payload

    def run(self,run_id,sim_ts,task,deadline=None):
        task=PolicyTask.model_validate(task)
        with self.store.connection() as db:
            observations=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_steps WHERE run_id=? ORDER BY step',(run_id,))]
            batches=db.execute("SELECT 1 FROM sqlite_master WHERE name='regional_batch_children'").fetchone()
            parent=db.execute('SELECT batch_id FROM regional_batch_children WHERE run_id=?',(run_id,)).fetchone() if batches else None
        owner=parent[0] if parent else run_id
        def stopped():
            if parent:
                with self.store.connection() as db:row=db.execute('SELECT body FROM regional_batches WHERE id=?',(owner,)).fetchone()
                if not row or json.loads(row[0])['cancelled']:return 'cancelled'
            return 'deadline' if deadline is not None and time.time()>=deadline else None
        def finish(status,recommendations=()):
            result=self.finish(status,list(recommendations),observations)
            if task.research_version:
                result['research_version']=task.research_version
                result['need_reviews']=[evidence_hold(n,status) for n in task.needs]
            return result
        limit=min(task.max_steps,self.settings.llm_max_calls)
        for step in range(len(observations),limit):
            if reason:=stopped():return finish(reason)
            try:payload=self.model_payload(task,observations,limit-step)
            except (ValueError,KeyError,TypeError):return finish('context_input_limit')
            try:decision=self.agents.call(run_id,sim_ts,'policy_decision',payload)
            except ValueError:return finish(stopped() or 'model_unavailable_or_budget')
            if reason:=stopped():return finish(reason)
            if decision.action=='finish':
                try:
                    result=finish('completed',self.recommendations(decision,observations,task))
                    if task.research_version:
                        needs={n.need_id:n for n in task.needs}
                        if len(decision.need_reviews)!=len(needs) or {r.need_id for r in decision.need_reviews}!=set(needs):raise ValueError('missing or duplicate need review')
                        reviews=[]
                        for review in decision.need_reviews:
                            need=needs[review.need_id]
                            try:reviews+=validate_reviews([review],task.model_copy(update={'needs':[need]}),result,observations,visible_policy_fields(payload))
                            except MaterialPolicyError as exc:reviews.append(evidence_hold(need,str(exc)))
                        result['need_reviews']=reviews
                        result['status']='needs_evidence' if any(r['decision']=='needs_evidence' for r in reviews) else 'completed'
                    return result
                except (ValueError,KeyError,TypeError):return finish('invalid_evidence')
            try:args=self.arguments(decision,observations,task)
            except ValueError:return finish('invalid_action')
            action=decision.model_dump()
            if decision.action!='policy_coverage' and any(o['action']['action']==decision.action and o['arguments']==args for o in observations):
                return finish('repeated_action')
            self.store.append_trace(run_id,sim_ts,'tool_call',{'step':step,'tool':decision.action,'arguments':args},'policy')
            if reason:=stopped():return finish(reason)
            if decision.action=='policy_field':
                policy=latest_details(observations)[args['policy_id']]['policy'];value=policy.get(args['field'])
                result={'policy_id':args['policy_id'],'field':args['field'],'value':value if isinstance(value,str) else None,
                    'frozen':True,'source_hash':digest(policy),'status':'available' if isinstance(value,str) and value else 'missing'}
            else:result=self.frozen_tool(owner,decision.action,args) if task.research_version=='regional-research-2' else self.call_tool(decision.action,args)
            observation={'action':action,'arguments':args,'result':result}
            with self.store.connection(write=True) as db:
                db.execute('INSERT INTO policy_steps VALUES (?,?,?)',(run_id,step,json.dumps(observation,ensure_ascii=False)))
                self.store._trace(db,run_id,sim_ts,'tool_result',{'step':step,'tool':decision.action,'result':result},'policy')
            observations.append(observation)
            if reason:=stopped():return finish(reason)
        return finish('step_limit')

    def arguments(self,decision,observations,task):
        if decision.action=='policy_field':
            detail=latest_details(observations).get(decision.policy_id)
            if not task.research_version or not detail or not detail.get('policy') or not decision.detail_field:raise ValueError('unobserved_policy_field')
            return {'policy_id':decision.policy_id,'field':decision.detail_field}
        if decision.action=='policy_search':
            if len(decision.query)>200 or not 1<=decision.page<=10000:raise ValueError('invalid_search')
            return {'scopes':task.scopes,'query':decision.query,'page':decision.page,'per_page':5}
        if decision.action in ('policy_detail','policy_details'):
            seen={p['id'] for o in observations if o['action']['action']=='policy_search' for p in o['result'].get('items',[]) if p['scope'] in task.scopes}
            ids=decision.policy_ids if decision.action=='policy_details' else [decision.policy_id]
            if not ids or len(ids)>5 or len(set(ids))!=len(ids) or not set(ids)<=seen:raise ValueError('unobserved_policy')
            return {'policy_ids':ids} if decision.action=='policy_details' else {'policy_id':decision.policy_id}
        return {}

    def recommendations(self,decision,observations,task):
        if len(decision.recommendations)>5:raise ValueError('invalid_evidence')
        details=latest_details(observations)
        result=[];seen=set()
        for item in decision.recommendations:
            detail=details.get(item.policy_id);p=detail['policy'] if detail else None
            if detail is None and task.research_version:
                resource=next((r for r in task.existing_resources if 'catalog:'+r['id']==item.policy_id),None)
                if resource:detail={'policy':catalog_policy(resource,task.scopes),'status':'catalog_snapshot','cached_at':resource.get('collected_at')};p=detail['policy']
            actual=p.get(item.field) if p else None
            # JSON/model transports may change CRLF to LF; preserve the provider text in the result.
            normalize=lambda text:text.replace('\r\n','\n').replace('\r','\n')
            if (not p or p['scope'] not in task.scopes or item.policy_id in seen or not item.value
                or not isinstance(actual,str) or normalize(actual)!=normalize(item.value)):raise ValueError('invalid_evidence')
            seen.add(item.policy_id)
            result.append({'policy':p,'evidence':{'field':item.field,'value':actual},'explanation':item.explanation,
                           'evidence_version':digest(p),'detail_status':detail['status'],'checked_at':detail.get('checked_at'),'cached_at':detail.get('cached_at'),
                           **({'conditions':detail.get('conditions'),'source_kind':'catalog' if item.policy_id.startswith('catalog:') else 'gov24',
                               'candidate_status':'reference_only','local_eligibility':'not_established'} if task.research_version else {})})
        return result

    def finish(self,status,recommendations,observations):
        coverage=next((o['result'].get('coverage',o['result']) for o in reversed(observations)
                       if 'coverage' in o['result'] or o['action']['action'] in ('policy_refresh','policy_coverage')),None)
        searches=[o for o in observations if o['action']['action']=='policy_search']
        records=latest_details(observations)
        completed=[]
        if searches:
            checked={pid for pid,detail in records.items() if detail.get('status')=='live'}
            queries={digest({'query':o['arguments'].get('query'),'scopes':o['arguments'].get('scopes')}):o['arguments'] for o in searches}
            for arguments in queries.values():
                pages=[o for o in searches if o['arguments'].get('query')==arguments.get('query') and o['arguments'].get('scopes')==arguments.get('scopes')]
                latest=max(pages,key=lambda o:o['arguments']['page']);page=latest['arguments']['page']
                searched={p['id'] for o in pages for p in o['result'].get('items',[])}
                snapshots=[o['result'].get('coverage') or {} for o in pages]
                current=all(c.get('source_complete') and not c.get('stale') and c.get('last_attempt',{}).get('status')=='success' for c in snapshots)
                same_snapshot=len({digest({k:c.get(k) for k in ('source','fetched_at','source_count','scopes')}) for c in snapshots})==1
                complete=(current and same_snapshot and latest['result'].get('next_page') is None and 'total' in latest['result']
                    and {o['arguments']['page'] for o in pages}==set(range(1,page+1))
                    and len(searched)==latest['result']['total'] and searched<=checked)
                if complete:completed.append({'query':arguments.get('query',''),'scopes':arguments.get('scopes')})
        complete=bool(searches and {'query':searches[-1]['arguments'].get('query',''),'scopes':searches[-1]['arguments'].get('scopes')} in completed)
        if status=='completed' and not recommendations:status='no_verified_candidates' if complete else 'search_incomplete'
        searched_ids={p['id'] for o in searches for p in o['result'].get('items',[])}
        details={pid:r for pid,r in records.items() if r.get('policy') and pid in searched_ids}
        selected_ids={r['policy']['id'] for r in recommendations}
        funnel={'retrieved':len(searched_ids),'details_checked':len(details),'selected':len(selected_ids),
                'display_target':3,'shortfall':max(0,3-len(selected_ids)),
                'not_selected':[{'policy_id':identifier,'title':detail['policy'].get('title',identifier),'reason':'not_selected_by_agent','detail_status':detail['status']} for identifier,detail in sorted(details.items()) if identifier not in selected_ids],
                'reason':'enough_candidates' if len(selected_ids)>=3 else 'fewer_relevant_verified_candidates' if complete and status=='completed' else 'search_incomplete' if status=='completed' else status}
        return {'candidate_funnel':funnel,'status':status,'recommendations':recommendations,'coverage':coverage,'steps':len(observations),
                'completed_queries':sorted({s['query'] for s in completed}),'completed_searches':completed,
                'search_complete_within_scope':complete,'search_scope':searches[-1]['arguments'] if searches else None,
                'mode':self.settings.llm_mode,'human_review_required':True,'allocation_performed':False,
                'all_policies_known':False,'limitation':LIMITATION}
