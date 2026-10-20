"""Bounded statistical collaboration over immutable tool observations."""
from time import time
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from backend.tools.regional_statistics import summary, run_tool


class WorkflowError(ValueError):
    """Public error codes defined by this module, never provider exception text."""


class AnalystPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    summary:str=Field(min_length=1,max_length=1200)
    priority_evidence_ids:list[str]=Field(max_length=5)


class StatisticsDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['lookup','finish','revise','human']
    tool:Literal['trend','source_check','sensitivity']
    reason:str=Field(min_length=1,max_length=1000)
    blocked_evidence_ids:list[str]=Field(max_length=50)


def observations(assessment):
    return [{'evidence_id':r['evidence_id'],**{k:r.get(k) for k in ('dong_nm','stage','stage_label','index_name','value','source_period','source_bands','flags')}} for r in assessment['segments']]


def model_observations(items):
    """Remove repeated source fields already supplied in facts; keep full stored tools."""
    result=[]
    for observation in items:
        view=dict(observation)
        if observation['tool']=='source_check':
            sources=list(dict.fromkeys(r['source_file'] for r in observation['items']))
            view['sources']=sources
            view['items']=[{k:r[k] for k in ('evidence_id','status','value_missing','stage_missing')} |
                           {'source_index':sources.index(r['source_file'])} for r in observation['items']]
        elif observation['tool']=='trend':
            view['series']=[{**series,'points':[{k:v for k,v in point.items() if k!='source_bands'} for point in series['points']]} for series in observation['series']]
        result.append(view)
    return result


def methodology(assessment):
    from backend.tools.regional_task import STAGES
    return {'version':assessment['methodology_version'],'stage_meanings':STAGES,
            'group_definition':', '.join(json.loads((Path(__file__).resolve().parents[2]/'rules/age_crosswalk.json').read_text())['concept'][assessment['task']['age_group']]),
            'provisional':True,'purpose':'within-region outreach priority; not individual diagnosis or absolute cross-region risk',
            'source_age_mapping':'source-specific ranges are retained; requested group labels are not measured population equivalence',
            'synthetic_future':assessment['metadata'].get('synthetic_future',False),
            'period_role':'synthetic future scenario; not an observation or calibrated forecast' if assessment['metadata'].get('synthetic_future') else 'execution reference only; not a monthly observation' if assessment['period_aggregate'] else 'observed month',
            'policy_role':'policy evidence is researched downstream; statistical tools do not establish policy eligibility'}


def analyze(agents,run_id,sim_ts,assessment,feedback=None):
    facts=observations(assessment)
    if feedback and feedback.get('statistics'):
        feedback={**feedback,'statistics':{**feedback['statistics'],'observations':model_observations(feedback['statistics']['observations'])}}
    plan=agents.call(run_id,sim_ts,'workflow_analyst',{'facts':facts,'task':assessment['task'],
        'feedback':feedback,'methodology':methodology(assessment),'provisional':True,'period_aggregate':assessment['period_aggregate']}).model_dump()
    allowed={r['evidence_id'] for r in facts}
    if len(set(plan['priority_evidence_ids']))!=len(plan['priority_evidence_ids']) or not set(plan['priority_evidence_ids'])<=allowed:
        raise WorkflowError('unobserved_analyst_evidence')
    return plan


def statistical_review(agents,settings,run_id,sim_ts,assessment,plan,emit,deadline,cached_observations=()):
    base=summary(assessment);retrieved=[];revised=None
    result={'status':'needs_human','summary':base,'observations':retrieved,'blocked_evidence_ids':base['blocked_evidence_ids'],
            'reason':'incomplete','revised_plan':None}
    allowed={r['evidence_id'] for r in assessment['segments']}
    try:
        for step in range(2):
            if time()>=deadline:raise WorkflowError('deadline')
            decision=agents.call(run_id,sim_ts,'workflow_statistics',{'task':assessment['task'],'plan':plan,
                'summary':base,'facts':observations(assessment),'methodology':methodology(assessment),'period_aggregate':assessment['period_aggregate'],
                'observations':model_observations(retrieved),'step':step,'available_tools':['trend','source_check','sensitivity']}).model_dump()
            if time()>=deadline:raise WorkflowError('deadline')
            blocked=decision['blocked_evidence_ids']
            if len(set(blocked))!=len(blocked) or not set(blocked)<=allowed:raise WorkflowError('unobserved_statistics_evidence')
            result['blocked_evidence_ids']=sorted(set(base['blocked_evidence_ids'])|set(blocked))
            result['reason']=decision['reason']
            emit(f'statistics-decision-{step}','statistics','regional_analyst' if decision['action']=='revise' else 'supervisor',decision)
            if decision['action']=='lookup':
                if step or retrieved:raise WorkflowError('statistics_lookup_limit')
                observation=next((o for o in cached_observations if o['tool']==decision['tool']),None)
                if observation is None:observation=run_tool(decision['tool'],settings,assessment)
                retrieved.append(observation)
                emit('statistics-tool','statistics','statistics',{'tool':decision['tool'],'observation':observation})
                continue
            if decision['action']=='human':return result
            if decision['action']=='revise':
                revised=analyze(agents,run_id,sim_ts,assessment,{'reason':decision['reason'],'statistics':result})
                if time()>=deadline:raise WorkflowError('deadline')
                if set(revised['priority_evidence_ids'])&set(result['blocked_evidence_ids']):raise WorkflowError('revision_retains_blocked_evidence')
                emit('analysis-revised','regional_analyst','statistics',{'plan':revised})
            if not retrieved:raise WorkflowError('missing_tool_observation')
            result.update(status='reviewed',revised_plan=revised,revision_check='observed_ids_and_missing_data' if revised else None)
            return result
        result['reason']='statistics_step_limit'
    except Exception as exc:
        result['reason']=str(exc) if isinstance(exc,WorkflowError) else 'model_or_tool_unavailable'
        result['error_type']=type(exc).__name__
        result['failure_kind']='exception'
    return result
