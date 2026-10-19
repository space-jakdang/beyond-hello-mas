"""Checkpointable regional analysis, review and evidence lookup transitions."""
from copy import deepcopy
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.agents.regional import context, cohort_id, issues
from backend.agents.regional_worker import lookup


class RegionalAudit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['accept', 'revise', 'lookup', 'human']
    targets: list[str] = Field(max_length=4)
    concerns: list[str] = Field(max_length=8)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def request(self):
        if (self.action == 'lookup') != bool(self.targets):
            raise ValueError('only lookup requires targets')
        return self


def prepare(observations, snapshots, max_calls=6, timeout_seconds=120):
    return {'observations': deepcopy(observations), 'snapshots': deepcopy(snapshots), 'retrieved': [],
            'proposals': [], 'reviews': [], 'requests': [], 'feedback': [], 'calls': 0,
            'max_calls': min(max_calls,6), 'deadline': time.time()+timeout_seconds,
            'status': 'running', 'plan': None, 'next': 'regional_analyst' if observations['facts'] else 'regional_finalize',
            'reason': None if observations['facts'] else 'no_observations'}


def from_classification(classification, mode, max_calls):
    observations=context(classification,mode)
    ids={r['id'] for r in observations['facts']}
    snapshots={cohort_id(r):{k:r.get(k) for k in ('source_file','source_period','source_bands','stage','flags','components','weekly')}
               for r in classification['segments'] if cohort_id(r) in ids}
    return prepare(observations,snapshots,max_calls)


def halt(state, reason):
    state.update(status='needs_human', plan=None, reason=reason, next='regional_finalize')
    return state


def advance(current, action, agents, run_id, sim_ts, emit):
    state=deepcopy(current)
    if state['next']=='regional_finalize':return state
    if time.time()>=state['deadline']:return halt(state,'deadline')
    try:
        if action=='lookup':
            request=state['requests'][-1]
            results=lookup(state['observations'],state['snapshots'],request['targets'])
            state['retrieved'].extend(results)
            emit(f"lookup-{state['calls']}",'supervisor','regional_analyst',{'request':request,'results':results})
            if any(r['status']=='unavailable' for r in results):return halt(state,'evidence_unavailable')
            state['next']='regional_analyst'
            return state
        if state['calls']>=state['max_calls']:return halt(state,'call_limit')
        state['calls']+=1
        shared={'observations':state['observations'],'retrieved':state['retrieved'],
                'remaining_calls':state['max_calls']-state['calls'],'step':state['calls']}
        if action=='analyze':
            decision=agents.call(run_id,sim_ts,'regional_planner',{**shared,
                'previous_plan':state['proposals'][-1] if state['proposals'] else None,'feedback':state['feedback']}).model_dump()
            if time.time()>=state['deadline']:return halt(state,'deadline')
            if decision['action']=='human':return halt(state,decision['reason'])
            if decision['action']=='lookup':
                state['requests'].append({'sender':'regional_analyst','targets':decision['targets'],'reason':decision['reason']})
                emit(f"request-{state['calls']}",'regional_analyst','supervisor',state['requests'][-1])
                state['next']='regional_lookup'
            else:
                state['proposals'].append(decision['plan'])
                emit(f"proposal-{len(state['proposals'])}",'regional_analyst','regional_reviewer',{'round':len(state['proposals']),'plan':decision['plan']})
                state['next']='regional_reviewer'
        elif action=='review':
            plan=state['proposals'][-1];checks=issues(plan,state['observations'])
            if state['observations'].get('verification_required') and not state['retrieved']:
                checks.append('Source verification requested; lookup required before acceptance.')
            review=agents.call(run_id,sim_ts,'regional_audit',{**shared,'plan':plan,'validation_issues':checks}).model_dump()
            if time.time()>=state['deadline']:return halt(state,'deadline')
            state['feedback']=list(dict.fromkeys(checks+review['concerns']))
            accepted=review['action']=='accept' and not state['feedback']
            state['reviews'].append({**review,'validation_issues':checks,
                'effective_decision':'accept' if accepted else 'revise' if review['action']=='accept' else review['action']})
            emit(f"review-{len(state['reviews'])}",'regional_reviewer','supervisor' if accepted or review['action'] in ('lookup','human') else 'regional_analyst',
                 {'decision':review['action'] if not (review['action']=='accept' and not accepted) else 'revise',
                  'concerns':state['feedback'],'reason':review['reason'],'targets':review['targets']})
            if accepted:state.update(status='reviewed',plan=plan,next='regional_finalize')
            elif review['action']=='human':return halt(state,review['reason'])
            elif review['action']=='lookup':
                state['requests'].append({'sender':'regional_reviewer','targets':review['targets'],'reason':review['reason']})
                state['feedback'].append(review['reason']);state['next']='regional_lookup'
            else:
                if not state['feedback']:state['feedback']=[review['reason']]
                state['next']='regional_analyst'
        else:raise ValueError('unknown regional action')
        return state
    except Exception as exc:
        return halt(state,type(exc).__name__)


def finish(state):
    return {'status':'reviewed' if state['status']=='reviewed' else 'needs_human','plan':state['plan'],
            'rounds':[{'round':i+1,'plan':plan} for i,plan in enumerate(state['proposals'])],
            'reviews':state['reviews'],'requests':state['requests'],'retrieved':state['retrieved'],
            'calls':state['calls'],'remaining_calls':max(0,state['max_calls']-state['calls']),
            'reason':state['reason'],'human_review_required':True}


def collaborate(agents, run_id, sim_ts, observations, snapshots, emit, max_calls=6, timeout_seconds=120):
    state=prepare(observations,snapshots,max_calls,timeout_seconds)
    while state['next']!='regional_finalize':
        action={'regional_analyst':'analyze','regional_reviewer':'review','regional_lookup':'lookup'}[state['next']]
        state=advance(state,action,agents,run_id,sim_ts,emit)
    return finish(state)
