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


class RegionalNote(BaseModel):
    model_config=ConfigDict(extra='forbid')
    fact_ids:list[str]=Field(min_length=1,max_length=8)
    implication:str=Field(min_length=1,max_length=500)
    hypothesis:str=Field(min_length=1,max_length=500)
    missing_evidence:list[str]=Field(min_length=1,max_length=5)


class StatisticsDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['lookup','finish','revise','human']
    tool:Literal['trend','source_check','sensitivity','policy_insights','regional_profile','regional_comparison']
    reason:str=Field(min_length=1,max_length=1000)
    blocked_evidence_ids:list[str]=Field(max_length=50)
    regional_notes:list[RegionalNote]=Field(default_factory=list,max_length=5)


def observations(assessment):
    from backend.tools.regional_resources import need_profile
    return [{'evidence_id':r['evidence_id'],**{k:r.get(k) for k in ('dong_nm','stage','index_name','value','source_period','source_bands','flags')},
             **({'source_age_band':r['source_age_band'],'assessment_status':r['assessment_status'],
                 'base_stage':r['base_stage'],'final_stage':r['final_stage'],
                 'card_alarm_status':r['card_alarm_status'],'card_week':r['card_week'],
                 'card_source_age_bands':r['card_source_age_bands']}
                if assessment['metadata'].get('analysis_version')=='v4' else {}),
             **({'observed_factors':need_profile(r)['observed_factors']} if r.get('components') else {})} for r in assessment['segments']]


def model_observations(items):
    """Remove repeated source fields already supplied in facts; keep full stored tools."""
    result=[]
    for observation in items:
        view=dict(observation)
        if observation['tool']=='regional_profile':
            from backend.context.analysis import model_briefing
            view=model_briefing({**observation,'areas':observation['areas'][:3]})
            view['unshown_dongs']=[a['dong_cd'] for a in observation['areas'][3:]]
        elif observation['tool']=='regional_comparison':
            view={**observation,'comparisons':observation['comparisons'][:12],'omitted_comparisons':max(0,len(observation['comparisons'])-12)}
        elif observation['tool']=='policy_insights':
            view={'tool':'policy_insights','version':observation['version'],'result_reference':'summary.insights'}
        elif observation['tool']=='sensitivity':
            view={**observation,'item_columns':['evidence_id','stages','base_stage_stable'],'items':[[i['evidence_id'],i['stages'],i['base_stage_stable']] for i in observation['items']]}
        elif observation['tool']=='source_check':
            if observation.get('tool_version')=='regional-statistics-v4':
                view['item_columns']=['evidence_id','source_age_band','source_stage','assessment_status','final_stage','selected_week','card_source_age_bands','card_evidence','card_alarm_status']
                view['items']=[[r[k] for k in view['item_columns']] for r in observation['items']]
            else:
                sources=list(dict.fromkeys(r['source_file'] for r in observation['items']))
                view['sources']=sources
                view['item_columns']=['evidence_id','status','value_missing','stage_missing','source_index']
                view['items']=[[r[k] for k in view['item_columns'][:-1]]+[sources.index(r['source_file'])] for r in observation['items']]
        elif observation['tool']=='trend':
            view['point_columns']=(['week','alarm_stage','baseline_status','source_age_bands','v_stages','n_stages']
                                   if observation.get('tool_version')=='regional-statistics-v4' else ['ym','value','change'])
            view['series']=[{**series,'points':[[point[k] for k in view['point_columns']] for point in series['points']]} for series in observation['series']]
        result.append(view)
    return result


def model_summary(summary):
    summary=dict(summary)
    if 'data_readiness' in summary:
        source=summary['data_readiness']
        summary['data_readiness']={**source,'cohorts':[{k:v for k,v in c.items() if k in ('id','observed','missing','comparison_ready','monthly_points','unavailable','synthetic','source_age_band','holds','insufficient_evidence','weekly_card_points','period_aggregate')} for c in source['cohorts']]}
    if 'insights' in summary:
        source=summary['insights']
        summary['insights']={**{k:v for k,v in source.items() if k in ('version','status','reason')},
                             'item_columns':['evidence_id','peer_count','risk_direction_difference','need_signals'],
                             'items':[[i['evidence_id'],i['comparison']['peer_count'],i['comparison']['risk_direction_difference'],i['measured_need_signals']] for i in source['items']]}
    needs=summary.get('policy_needs')
    return {**summary,'policy_needs':{k:v for k,v in needs.items() if k!='profiles'}} if needs else summary


def methodology(assessment):
    if assessment['metadata'].get('analysis_version')=='v4':
        from backend.tools.region_stage_v4 import STAGE_LABEL
        task=assessment['task']
        return {'version':assessment['methodology_version'],'stage_meanings':STAGE_LABEL,
                'stage_scope':'Source stages -1/0 distinguish insufficient evidence and population hold. Assessed stages 1-5 are ordinal review priorities; no continuous index or cross-region absolute risk.',
                'source_age_band':task['source_age_band'],'source_age_coverage':task['source_age_band'],
                'selected_card_week':task['card_week'],'card_rule':'min(V,N); strong alone raises an assessed base stage by one, capped at five; no hold/insufficient status uplift',
                'period_role':'2025 stage input is a period aggregate; selected card week is the only weekly observation used for the final stage.',
                'continuous_metric':False,'provisional':True,
                'purpose':'within-source-group outreach review; not individual diagnosis, eligibility, or absolute cross-region risk',
                'need_mapping':'regional-needs-3: stage and card signals alone do not establish a service need; require source factor definitions and field confirmation'}
    from backend.tools.regional_task import STAGES
    return {'version':assessment['methodology_version'],'stage_meanings':STAGES,'stage_scope':'S1/v3 base stages 1-3; other source/rank stages 1-5. Common priority criterion is unvalidated; no cross-scale comparison. Weekly exploration is separate.',
            'group_definition':', '.join(json.loads((Path(__file__).resolve().parents[2]/'rules/age_crosswalk.json').read_text())['concept'][assessment['task']['age_group']]),
            'provisional':True,'purpose':'within-region outreach priority; not individual diagnosis or absolute cross-region risk',
            'need_mapping':'regional-needs-2: source factors are uninterpreted observations, not verified service needs; S1/v3 support only a relationship outreach hypothesis, including stage 1',
            'source_age_mapping':'source-specific ranges are retained; requested group labels are not measured population equivalence',
            'synthetic_future':assessment['metadata'].get('synthetic_future',False),
            'period_role':'synthetic future scenario; not an observation or calibrated forecast' if assessment['metadata'].get('synthetic_future') else 'execution reference only; not a monthly observation' if assessment['period_aggregate'] else 'observed month',
            'policy_role':'policy evidence is researched downstream; statistical tools do not establish policy eligibility'}


def analyze(agents,run_id,sim_ts,assessment,feedback=None):
    facts=observations(assessment)
    if feedback and feedback.get('statistics'):
        feedback={**feedback,'statistics':{**feedback['statistics'],'summary':model_summary(feedback['statistics']['summary']),'observations':model_observations(feedback['statistics']['observations'])}}
    plan=agents.call(run_id,sim_ts,'workflow_analyst',{'facts':facts,'task':assessment['task'],
        'feedback':feedback,'methodology':methodology(assessment),'provisional':True,'period_aggregate':assessment['period_aggregate'],**context_payload(assessment)}).model_dump()
    allowed={r['evidence_id'] for r in facts}
    if len(set(plan['priority_evidence_ids']))!=len(plan['priority_evidence_ids']) or not set(plan['priority_evidence_ids'])<=allowed:
        raise WorkflowError('unobserved_analyst_evidence')
    return plan


def context_payload(assessment,plan=None):
    if 'regional_context' not in assessment:return {}
    from backend.context.analysis import briefing,model_briefing
    codes={r['dong_cd'] for r in assessment['segments'] if not plan or not plan['priority_evidence_ids'] or r['evidence_id'] in plan['priority_evidence_ids']}
    available=sorted(codes)
    view=model_briefing(briefing(assessment['regional_context'],set(available[:3])))
    view['available_dongs']=available;view['unshown_dongs']=available[3:]
    return {'regional_context':view}


def statistical_review(agents,settings,run_id,sim_ts,assessment,plan,emit,deadline,cached_observations=()):
    base=summary(assessment);retrieved=[];revised=None
    current=assessment['metadata'].get('review_contract_version')=='statistics-review-2'
    result={'status':'needs_human','summary':base,'observations':retrieved,'blocked_evidence_ids':base['blocked_evidence_ids'],
            'reason':'incomplete','revised_plan':None}
    if current:result.update(review_version='statistics-review-2',initial_plan=plan,review_history=[])
    allowed={r['evidence_id'] for r in assessment['segments']}
    try:
        modern=current or assessment['metadata'].get('statistics_version')=='2'
        for step in range(5 if current else 4 if modern else 2):
            if time()>=deadline:raise WorkflowError('deadline')
            final=current and revised is not None
            context={'review_version':'statistics-review-2','review_phase':'final' if final else 'initial',
                     'revision_reason':result['reason'] if final else None} if current else {}
            tools=['trend','source_check','sensitivity']+(['regional_profile','regional_comparison'] if 'regional_context' in assessment else [])+([] if current else ['policy_insights'] if modern else [])
            decision=agents.call(run_id,sim_ts,'workflow_statistics',{'task':assessment['task'],'plan':plan,
                'summary':model_summary(base),'facts':observations(assessment),'methodology':methodology(assessment),'period_aggregate':assessment['period_aggregate'],
                'observations':model_observations(retrieved),'step':step,'available_tools':[] if final else [tool for tool in tools if not any(o['tool']==tool for o in retrieved)] if current else tools,
                'remaining_lookups':0 if final else (3 if modern else 1)-len(retrieved),**context,**context_payload(assessment,plan)}).model_dump()
            if time()>=deadline:raise WorkflowError('deadline')
            from backend.context.analysis import validate_notes,observed_ids
            if decision['action']=='lookup' and 'regional_context' not in assessment and decision['tool'].startswith('regional_'):raise WorkflowError('regional_context_not_available')
            extra_ids={identifier for o in model_observations(retrieved) if o['tool']=='regional_profile' for identifier in observed_ids(o)}
            extra_ids.update(identifier for o in model_observations(retrieved) if o['tool']=='regional_comparison' for c in o['comparisons'] for identifier in [c['fact_id'],*c['peer_fact_ids']])
            notes=validate_notes(decision.get('regional_notes',[]),assessment,context_payload(assessment,plan).get('regional_context'),extra_ids)
            if notes or 'regional_notes' not in result:result['regional_notes']=notes
            blocked=decision['blocked_evidence_ids']
            if len(set(blocked))!=len(blocked) or not set(blocked)<=allowed:raise WorkflowError('unobserved_statistics_evidence')
            result['blocked_evidence_ids']=sorted(set(base['blocked_evidence_ids'])|set(blocked))
            result['reason']=decision['reason']
            if current:result['review_history'].append({'phase':context['review_phase'],**decision})
            emit(f'statistics-decision-{step}','statistics','regional_analyst' if decision['action']=='revise' else 'supervisor',decision)
            if final and decision['action'] in ('lookup','revise'):raise WorkflowError('final_review_requires_finish_or_human')
            if decision['action']=='lookup':
                if current and decision['tool']=='policy_insights':raise WorkflowError('statistics_duplicate_summary_lookup')
                if len(retrieved)>=(3 if modern else 1) or any(o['tool']==decision['tool'] for o in retrieved):raise WorkflowError('statistics_lookup_limit')
                if not modern and decision['tool']=='policy_insights':raise WorkflowError('legacy_tool_not_available')
                observation=next((o for o in cached_observations if o['tool']==decision['tool']),None)
                if observation is not None and decision['tool'].startswith('regional_'):
                    from backend.tools.indicators import digest
                    if observation.get('input_hash')!=digest({code:p['input_hash'] for code,p in assessment['regional_context'].items()}):raise WorkflowError('regional_cached_input_mismatch')
                if observation is None:observation=run_tool(decision['tool'],settings,assessment)
                retrieved.append(observation)
                emit('statistics-tool' if not modern else f'statistics-tool-{len(retrieved)}','statistics','statistics',{'tool':decision['tool'],'observation':observation})
                continue
            if decision['action']=='human':return result
            if decision['action']=='revise':
                revised=analyze(agents,run_id,sim_ts,assessment,{'reason':decision['reason'],'statistics':result})
                if time()>=deadline:raise WorkflowError('deadline')
                if set(revised['priority_evidence_ids'])&set(result['blocked_evidence_ids']):raise WorkflowError('revision_retains_blocked_evidence')
                emit('analysis-revised','regional_analyst','statistics',{'plan':revised})
                if current:
                    result['revised_plan']=revised;plan=revised
                    continue
            if current and set(plan['priority_evidence_ids'])&set(result['blocked_evidence_ids']):raise WorkflowError('review_retains_blocked_evidence')
            if not retrieved and not current:raise WorkflowError('missing_tool_observation')
            from backend.tools.policy_insights import persistence
            result['persistence']=[p for o in retrieved if o['tool']=='trend' for p in persistence(o)]
            result.update(status='reviewed',revised_plan=revised,revision_check=('final_statistics_review' if current else 'observed_ids_and_missing_data') if revised else None)
            return result
        result['reason']='statistics_step_limit'
    except Exception as exc:
        result['reason']=str(exc) if isinstance(exc,WorkflowError) else 'model_or_tool_unavailable'
        result['error_type']=type(exc).__name__
        result['failure_kind']='exception'
    return result
