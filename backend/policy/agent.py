"""Supervisor-scoped ReAct worker. Tool observations, not private reasoning, are persisted."""
import asyncio
import json
import os
import sys
from typing import Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, ConfigDict, Field
from backend.app.config import ROOT
from backend.policy.service import SCOPES, Scope, LIMITATION


class PolicyTask(BaseModel):
    model_config=ConfigDict(extra='forbid')
    goal:str=Field(min_length=1,max_length=1000)
    scopes:list[Scope]=Field(default_factory=lambda:SCOPES.copy(),min_length=1,max_length=5)
    query:str=Field(default='',max_length=200)
    max_steps:int=Field(default=6,ge=1,le=10)


class PolicyEvidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    policy_id:str
    field:Literal['title','eligibility','criteria','support','deadline']
    value:str
    explanation:str


class PolicyDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['policy_coverage','policy_refresh','policy_search','policy_detail','finish']
    query:str
    page:int
    policy_id:str | None
    recommendations:list[PolicyEvidence]
    reason:str


def fake_decision(payload):
    observations=payload['observations']
    result={'action':'policy_refresh','query':'','page':1,'policy_id':None,'recommendations':[],
            'reason':'fake: deterministic protocol fixture, not model reasoning'}
    if not observations:return result
    last=observations[-1]['result'];tool=observations[-1]['action']['action']
    if tool=='policy_refresh' and last.get('status')=='cached':
        result.update(action='policy_search',query=payload['task']['query'])
    elif tool=='policy_search' and last.get('items'):
        result.update(action='policy_detail',policy_id=last['items'][0]['id'])
    else:
        result['action']='finish'
        if tool=='policy_detail' and last.get('policy'):
            p=last['policy'];result['recommendations']=[{'policy_id':p['id'],'field':'title','value':p['title'],
                'explanation':'fake: 조회된 정책 후보입니다. 적격성은 담당자가 확인해야 합니다.'}]
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

    async def remote(self,tool,args):
        env={'DATA_MODE':self.settings.data_mode,'LLM_MODE':'fake',
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
            timeout=60+self.settings.policy_timeout_seconds+5 if tool=='policy_refresh' else 2*self.settings.policy_timeout_seconds+10
            return await asyncio.wait_for(self.remote(tool,args),timeout)
        try:return asyncio.run(invoke())
        except Exception as exc:return {'status':'error','error':type(exc).__name__}

    def run(self,run_id,sim_ts,task):
        task=PolicyTask.model_validate(task)
        with self.store.connection() as db:
            observations=[json.loads(r[0]) for r in db.execute('SELECT body FROM policy_steps WHERE run_id=? ORDER BY step',(run_id,))]
        limit=min(task.max_steps,self.settings.llm_max_calls)
        for step in range(len(observations),limit):
            payload={'task':task.model_dump(),'observations':[compact(o) for o in observations],'steps_remaining':limit-step,
                     'tools':['policy_coverage','policy_refresh','policy_search','policy_detail','finish']}
            try:decision=self.agents.call(run_id,sim_ts,'policy_decision',payload)
            except ValueError:return self.finish('model_unavailable_or_budget',[],observations)
            if decision.action=='finish':
                try:return self.finish('completed',self.recommendations(decision,observations,task),observations)
                except ValueError:return self.finish('invalid_evidence',[],observations)
            try:args=self.arguments(decision,observations,task)
            except ValueError:return self.finish('invalid_action',[],observations)
            action=decision.model_dump()
            if decision.action!='policy_coverage' and any(o['action']['action']==decision.action and o['arguments']==args for o in observations):
                return self.finish('repeated_action',[],observations)
            self.store.append_trace(run_id,sim_ts,'tool_call',{'step':step,'tool':decision.action,'arguments':args},'policy')
            result=self.call_tool(decision.action,args)
            observation={'action':action,'arguments':args,'result':result}
            with self.store.connection(write=True) as db:
                db.execute('INSERT INTO policy_steps VALUES (?,?,?)',(run_id,step,json.dumps(observation,ensure_ascii=False)))
                self.store._trace(db,run_id,sim_ts,'tool_result',{'step':step,'tool':decision.action,'result':result},'policy')
            observations.append(observation)
        return self.finish('step_limit',[],observations)

    def arguments(self,decision,observations,task):
        if decision.action=='policy_search':
            if len(decision.query)>200 or not 1<=decision.page<=10000:raise ValueError('invalid_search')
            return {'scopes':task.scopes,'query':decision.query,'page':decision.page,'per_page':5}
        if decision.action=='policy_detail':
            seen={p['id'] for o in observations if o['action']['action']=='policy_search' for p in o['result'].get('items',[]) if p['scope'] in task.scopes}
            if decision.policy_id not in seen:raise ValueError('unobserved_policy')
            return {'policy_id':decision.policy_id}
        return {}

    def recommendations(self,decision,observations,task):
        details={o['result']['policy']['id']:o['result'] for o in observations
                 if o['action']['action']=='policy_detail' and o['result'].get('policy')}
        result=[];seen=set()
        for item in decision.recommendations:
            detail=details.get(item.policy_id);p=detail['policy'] if detail else None
            if (not p or p['scope'] not in task.scopes or item.policy_id in seen or not item.value
                or p.get(item.field)!=item.value):raise ValueError('invalid_evidence')
            seen.add(item.policy_id)
            result.append({'policy':p,'evidence':{'field':item.field,'value':item.value},'explanation':item.explanation,
                           'detail_status':detail['status'],'checked_at':detail.get('checked_at'),'cached_at':detail.get('cached_at')})
        return result

    def finish(self,status,recommendations,observations):
        coverage=next((o['result'].get('coverage',o['result']) for o in reversed(observations)
                       if 'coverage' in o['result'] or o['action']['action'] in ('policy_refresh','policy_coverage')),None)
        if status=='completed' and not recommendations:status='no_verified_candidates'
        return {'status':status,'recommendations':recommendations,'coverage':coverage,'steps':len(observations),
                'mode':self.settings.llm_mode,'human_review_required':True,'allocation_performed':False,
                'all_policies_known':False,'limitation':LIMITATION}
