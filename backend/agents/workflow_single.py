"""Evaluation-only single agent, using the same frozen statistical tools and ledger."""
from time import time
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from backend.agents.workflow import AnalystPlan,WorkflowError,methodology,observations,model_summary,model_observations
from backend.tools.regional_statistics import summary,run_tool


class SingleDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['lookup','finish','human']
    tool:Literal['trend','source_check','sensitivity']
    reason:str=Field(min_length=1,max_length=1000)
    plan:AnalystPlan|None


def run(agents,settings,run_id,sim_ts,assessment,emit,deadline):
    base=summary(assessment);retrieved=[]
    stats={'status':'needs_human','reason':'incomplete','summary':base,'observations':retrieved,
           'blocked_evidence_ids':base['blocked_evidence_ids'],'review_mode':'single_self_review'}
    allowed={r['evidence_id'] for r in assessment['segments']}
    try:
        for step in range(4):
            if time()>=deadline:raise WorkflowError('deadline')
            tools=[tool for tool in ('trend','source_check','sensitivity') if not any(o['tool']==tool for o in retrieved)]
            decision=agents.call(run_id,sim_ts,'workflow_single',{'task':assessment['task'],'facts':observations(assessment),
                'methodology':methodology(assessment),'summary':model_summary(base),'observations':model_observations(retrieved),
                'available_tools':tools,'step':step}).model_dump()
            if time()>=deadline:raise WorkflowError('deadline')
            stats['reason']=decision['reason']
            emit(f'single-decision-{step}','regional_analyst','supervisor',decision)
            if decision['action']=='human':return None,stats
            if decision['action']=='lookup':
                if decision['tool'] not in tools:raise WorkflowError('statistics_lookup_limit')
                observation=run_tool(decision['tool'],settings,assessment);retrieved.append(observation)
                emit(f'single-tool-{len(retrieved)}','regional_analyst','regional_analyst',{'observation':observation})
                continue
            plan=decision['plan']
            if plan is None or len(set(plan['priority_evidence_ids']))!=len(plan['priority_evidence_ids']) or not set(plan['priority_evidence_ids'])<=allowed:
                raise WorkflowError('unobserved_analyst_evidence')
            if set(plan['priority_evidence_ids'])&set(base['blocked_evidence_ids']):raise WorkflowError('review_retains_blocked_evidence')
            stats['status']='reviewed'
            return plan,stats
        stats['reason']='statistics_step_limit'
    except Exception as exc:
        stats.update(reason=str(exc) if isinstance(exc,WorkflowError) else 'model_or_tool_unavailable',error_type=type(exc).__name__,failure_kind='exception')
    return None,stats
