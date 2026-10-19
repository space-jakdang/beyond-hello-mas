"""Bounded analyst/reviewer exchange over immutable regional tool observations."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

Limitation=Literal['not_individual','incomparable_regions','period_aggregate','missing_values','synthetic']


class RegionalPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    summary:str=Field(min_length=1,max_length=1500)
    focus_ids:list[str]=Field(min_length=1,max_length=8)
    limitations:list[Limitation]


class RegionalReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    decision:Literal['accept','revise']
    concerns:list[str]=Field(max_length=8)


def cohort_id(row):
    return '/'.join(row[k] for k in ('dong_cd','sex','age_group'))


def context(classification,mode):
    rows=classification['segments']
    # One representative per district/sex/age; keep the full population count visible.
    groups={}
    for row in sorted(rows,key=lambda r:(-(r['stage'] or 0),cohort_id(r))):
        groups.setdefault((row['sgg'],row['sex'],row['age_group']),row)
    facts=[{'id':cohort_id(r),**{k:r.get(k) for k in ('dong_nm','stage','index_name','value','source_period','source_bands')}} for _,r in sorted(groups.items())]
    required=['not_individual','incomparable_regions']
    if classification.get('period_aggregate'):required.append('period_aggregate')
    if any(r['stage'] is None for r in rows):required.append('missing_values')
    if mode=='sample':required.append('synthetic')
    return {'facts':facts,'total_cohorts':len(rows),'selection':'highest-stage representative within each district/sex/age; not a cross-region ranking',
            'required_limitations':required,'goal':'관측 근거로 담당자가 먼저 검토할 지역 집단을 제안하고 불확실성을 밝히세요. 개인 판정·예산 배분은 하지 마세요.'}


def issues(plan,observations):
    allowed={r['id'] for r in observations['facts']}
    problems=[]
    if len(set(plan['focus_ids']))!=len(plan['focus_ids']) or not set(plan['focus_ids'])<=allowed:
        problems.append('focus_ids must be unique observed cohort IDs')
    missing=set(observations['required_limitations'])-set(plan['limitations'])
    if missing:problems.append('missing limitations: '+', '.join(sorted(missing)))
    return problems


def collaborate(agents,run_id,sim_ts,observations,emit):
    feedback=[];previous=None;rounds=[]
    emit('delegate','supervisor','regional_analyst',{'goal':observations['goal'],'observations':observations})
    if not observations['facts']:
        return {'status':'needs_human','plan':None,'rounds':[],'reason':'no_observations','human_review_required':True}
    for number in (1,2):
        try:
            plan=agents.call(run_id,sim_ts,'regional_analyst',{'observations':observations,'previous_plan':previous,'feedback':feedback,'round':number}).model_dump()
            emit(f'proposal-{number}','regional_analyst','regional_reviewer',{'round':number,'plan':plan})
            checks=issues(plan,observations)
            review=agents.call(run_id,sim_ts,'regional_reviewer',{'observations':observations,'plan':plan,'validation_issues':checks,'round':number}).model_dump()
            feedback=list(dict.fromkeys(checks+review['concerns']))
            if review['decision']=='revise' and not feedback:feedback=['Reviewer requested revision without a concrete reason; human verification needed.']
            accepted=review['decision']=='accept' and not feedback
            rounds.append({'round':number,'plan':plan,'review':review,'validation_issues':checks})
            emit(f'review-{number}','regional_reviewer','supervisor' if accepted or number==2 else 'regional_analyst',
                 {'round':number,'decision':'accept' if accepted else 'revise','concerns':feedback})
            if accepted:
                emit('decision','supervisor','match',{'decision':'submit_for_human_approval','focus_ids':plan['focus_ids']})
                return {'status':'reviewed','plan':plan,'rounds':rounds,'human_review_required':True}
            previous=plan
        except Exception as exc:
            emit('failure','supervisor','match',{'decision':'needs_human','error_type':type(exc).__name__})
            return {'status':'needs_human','plan':None,'rounds':rounds,'reason':type(exc).__name__,'human_review_required':True}
    emit('decision','supervisor','match',{'decision':'needs_human','concerns':feedback})
    return {'status':'needs_human','plan':None,'rounds':rounds,'reason':'revision_limit','human_review_required':True}
