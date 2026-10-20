from pydantic import BaseModel,ConfigDict,Field


class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    evidence_id:str
    resource_ids:list[str]=Field(max_length=3)
    reason:str=Field(min_length=1,max_length=500)


class MatchingPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    selections:list[Selection]=Field(max_length=50)
    summary:str=Field(min_length=1,max_length=1200)


def select(agents,run_id,sim_ts,rows,statistics):
    eligible=[r for r in rows if r['recommendations']]
    if not eligible:return rows,{'status':'needs_human','summary':'근거 또는 필수 조건을 충족하는 자원이 없어 확인이 필요합니다.'}
    choices=[{'evidence_id':r['evidence_id'],'needs':r['needs'],'stage':r['stage'],
        'candidates':[{'id':c['id'],'name':c['name'],'needs':c['needs']} for c in r['recommendations']]} for r in eligible]
    plan=agents.call(run_id,sim_ts,'workflow_matching',{'choices':choices,'statistics':{
        'status':statistics['status'],'reason':statistics['reason'],'summary':statistics['summary']}}).model_dump()
    by_id={r['evidence_id']:r for r in eligible};chosen={}
    for item in plan['selections']:
        eid=item['evidence_id'];ids=item['resource_ids']
        if eid not in by_id or eid in chosen or len(ids)!=len(set(ids)) or not set(ids)<={c['id'] for c in by_id[eid]['recommendations']}:
            raise ValueError('unverified matching selection')
        chosen[eid]=item
    result=[]
    for row in rows:
        selection=chosen.get(row['evidence_id'])
        recommendations=[c for c in row['recommendations'] if selection and c['id'] in selection['resource_ids']]
        result.append({**row,'recommendations':recommendations,'shortfall':3-len(recommendations),
            'uncovered_needs':sorted(set(row['needs'])-{n for c in recommendations for n in c['needs']}),
            'reason':selection['reason'] if selection else row['reason'] or 'agent_deferred',
            'status':'conditional_recommendation' if recommendations else 'needs_human'})
    return result,{'status':'reviewed','summary':plan['summary']}
