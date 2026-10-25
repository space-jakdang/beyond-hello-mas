"""Per-need decisions cite verified policy fields and frozen regional facts."""
from typing import Literal
from datetime import date
import json
import re
from pydantic import BaseModel,ConfigDict,Field,StrictInt
from backend.policy.design_contracts import Citation


class MaterialPolicyError(ValueError):
    """A candidate needs more evidence before it can support local guidance."""


class ResearchNeed(BaseModel):
    model_config=ConfigDict(extra='forbid')
    need_id:str=Field(min_length=1,max_length=150)
    target_group:str=Field(pattern=r'^[MF]/(youth|midlife|prime|elderly|20대|30대|40대|50대|60대|60대\+|70대\+)$')
    need:str=Field(min_length=1,max_length=100)
    evidence_ids:list[str]=Field(min_length=1,max_length=8)
    requirements:list[str]=Field(min_length=1,max_length=5)
    verified_gaps:list[str]=Field(default_factory=list,max_length=5)
    queries:list[str]=Field(default_factory=list,max_length=5)
    source_bands:dict[str,list[str]]=Field(default_factory=dict)
    source_age_ranges:list[tuple[StrictInt,StrictInt]]=Field(default_factory=list,max_length=8)


class NeedReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    need_id:str
    decision:Literal['reuse_existing','adapt_existing','new_design_needed','needs_evidence']
    policy_ids:list[str]=Field(max_length=5)
    citations:list[Citation]=Field(max_length=10)
    regional_fact_ids:list[str]=Field(max_length=8)
    unmet_requirements:list[str]=Field(max_length=5)
    search_query:str | None = None
    proposed_channel:str | None = Field(default=None,min_length=1,max_length=200)
    reason:str=Field(min_length=1,max_length=800)
    missing_evidence:list[str]=Field(min_length=1,max_length=8)


def evidence_hold(need,reason):
    row=NeedReview(need_id=need.need_id,decision='needs_evidence',policy_ids=[],citations=[],
        regional_fact_ids=[],unmet_requirements=[],reason=reason,missing_evidence=[reason]).model_dump()
    if need.source_bands:row.update(source_bands=need.source_bands,source_age_ranges=need.source_age_ranges)
    return row | {'target_group':need.target_group,'need':need.need,'evidence_ids':need.evidence_ids,
        'requirements':need.requirements,'guidance':[],'outreach_draft':None,
        'individual_eligibility_verified':False,'capacity_verified':False}


def regional_briefing(profiles):
    from backend.context.analysis import briefing
    areas={p['request']['dong_cd']:p for p in profiles}
    if len(areas)!=len(profiles):raise ValueError('duplicate regional profile')
    return briefing(areas)


def latest_details(observations):
    records={}
    for observation in observations:
        action=observation['action']['action'];arguments=observation.get('arguments',{})
        if action not in ('policy_detail','policy_details'):continue
        identifiers=arguments.get('policy_ids',[]) if action=='policy_details' else [arguments.get('policy_id')]
        for identifier in identifiers:
            if identifier:records[identifier]={'status':'unavailable','policy':None}
        rows=observation['result'].get('items',[]) if action=='policy_details' else [observation['result']]
        for row in rows:
            if row.get('policy'):records[row['policy']['id']]=row
    return records


def catalog_policy(resource,scopes):
    mapping={'KR':'central','11':'seoul','11230':'gangnam','32':'gangwon','32010':'chuncheon'}
    applicable=[mapping[code] for code in resource['jurisdiction'] if code in mapping and mapping[code] in scopes]
    if not applicable:raise ValueError('catalog_outside_scope')
    return {'id':'catalog:'+resource['id'],'title':resource['name'],'scope':applicable[0],
        'support':resource['evidence'],'eligibility':resource['eligibility'],'application':None,
        'deadline':resource.get('valid_until'),'contact':None,'agency':None,'url':resource.get('source_url')}


def visible_policy_fields(payload):
    fields={}
    for resource in payload['task']['existing_resources']:
        policy=catalog_policy(resource,payload['task']['scopes'])
        fields[policy['id']]=policy
    for observation in payload['observations']:
        action=observation['action']['action'];result=observation['result']
        rows=result.get('items',[]) if action=='policy_details' else [result] if action=='policy_detail' else []
        for row in rows:
            if row.get('policy'):fields[row['policy']['id']]=dict(row['policy'])
        if action=='policy_field' and result.get('status')=='available':
            fields.setdefault(result['policy_id'],{})[result['field']]=result['value']
    return fields


def target_checks(candidate,need,task):
    from backend.app.contracts import Resource
    from backend.context.contracts import ContextRequest
    from backend.tools.matching import MatchRequest,filter_catalog
    from backend.tools.regional_resources import source_age_ranges
    requests=[ContextRequest.model_validate(p['request']) for p in task.regional_profiles]
    if not requests or len({(r.sgg,r.as_of) for r in requests})!=1:raise MaterialPolicyError('regional_target_scope_missing')
    request=requests[0];sex,group=need.target_group.split('/')
    if task.research_version=='regional-research-2' or need.source_bands or need.source_age_ranges:
        ages=source_age_ranges(need.source_bands)
        if not ages or ages!=need.source_age_ranges:raise MaterialPolicyError('source_age_definition_unavailable')
    else:
        from pathlib import Path
        definitions=json.loads((Path(__file__).resolve().parents[2]/'rules/age_crosswalk.json').read_text())['concept']
        ages=source_age_ranges({'concept':definitions.get(group,[])})
    if not ages:raise MaterialPolicyError('source_age_definition_unavailable')
    low,high=ages[0][0],ages[-1][1]
    if candidate.get('source_kind')=='catalog':
        raw=candidate['resource'];resource=Resource.model_validate({k:v for k,v in raw.items() if k in Resource.model_fields})
        query=MatchRequest(sgg=request.sgg,age_min=low,age_max=high,needs=[need.need],intensity=resource.intensity,as_of=request.as_of)
        eligible,_,checks=filter_catalog([resource],query,regional_ages=ages)
        if not eligible:raise MaterialPolicyError('policy_target_or_time_mismatch')
        return checks[resource.id]
    policy=candidate['policy'];conditions=candidate.get('conditions')
    scopes={'11230':{'central','seoul','gangnam'},'32010':{'central','gangwon','chuncheon'}}
    if policy.get('scope') not in scopes[request.sgg]&set(task.scopes):raise MaterialPolicyError('policy_jurisdiction_mismatch')
    if not isinstance(conditions,dict) or conditions.get('서비스ID')!=policy['id']:raise MaterialPolicyError('material_policy_target_missing')
    # Official supportConditions defines these fields; other flags remain individual checks.
    start,end=conditions.get('JA0110'),conditions.get('JA0111')
    if type(start) is not int or type(end) is not int or not 0<=start<=end<=150:raise MaterialPolicyError('material_policy_target_missing')
    flag=conditions.get('JA0101' if sex=='M' else 'JA0102')
    if flag not in ('Y','N'):raise MaterialPolicyError('material_policy_target_missing')
    covered=[[max(start,low),min(end,high)] for low,high in ages if start<=high and end>=low]
    if flag=='N' or not covered:raise MaterialPolicyError('policy_target_mismatch')
    def dates(text):
        try:return [date(int(y),int(m),int(d)) for y,m,d in re.findall(r'(?<!\d)(\d{4})\s*(?:[-./]|년)\s*(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})(?!\d)',str(text or ''))]
        except ValueError as exc:raise MaterialPolicyError('material_policy_time_missing') from exc
    deadlines=dates(policy.get('deadline'));updated=dates(policy.get('source_updated_at'))
    if deadlines and max(deadlines)<request.as_of or updated and max(updated)>request.as_of:raise MaterialPolicyError('policy_time_mismatch')
    full=all(start<=low and end>=high for low,high in ages)
    return {'condition_checks':{'sex':'pass','age':'pass' if full else 'unknown'},
            'age_coverage':'full' if full else 'partial','eligible_age_ranges':covered}


def validate_reviews(reviews,task,result,observations=(),shown=None):
    needs={n.need_id:n for n in task.needs}
    if len(reviews)!=len(needs) or {r.need_id for r in reviews}!=set(needs):raise ValueError('missing or duplicate need review')
    candidates={r['policy']['id']:r for r in result['recommendations']}
    for identifier,detail in latest_details(observations).items():
        candidates[identifier]=detail if not detail.get('policy') or detail['policy']['scope'] in task.scopes else {'status':'unavailable','policy':None}
    for resource in task.existing_resources:
        candidates['catalog:'+resource['id']]={'policy':catalog_policy(resource,task.scopes),'resource':resource,'source_kind':'catalog','verification':resource.get('verification')}
    from backend.context.analysis import observed_ids
    view=regional_briefing(task.regional_profiles)
    normalize=lambda text:text.replace('\r\n','\n').replace('\r','\n')
    known=observed_ids(view)
    output=[]
    for review in reviews:
        row=review.model_dump();need=needs[review.need_id]
        if not set(review.regional_fact_ids)<=known:raise ValueError('unobserved regional fact')
        if len(set(review.policy_ids))!=len(review.policy_ids) or not set(review.policy_ids)<=set(candidates):raise ValueError('unverified policy review')
        if any(not candidates[pid].get('policy') for pid in review.policy_ids):raise MaterialPolicyError('policy_detail_unavailable')
        substantive=set()
        for citation in review.citations:
            if citation.policy_id not in review.policy_ids:raise ValueError('policy citation mismatch')
            actual=candidates[citation.policy_id]['policy'].get(citation.field)
            if not isinstance(actual,str) or normalize(citation.quote) not in normalize(actual):raise ValueError('policy citation mismatch')
            if shown is not None:
                visible=shown.get(citation.policy_id,{}).get(citation.field)
                if not isinstance(visible,str) or normalize(citation.quote) not in normalize(visible):raise ValueError('policy quote outside model view')
            if citation.field in ('support','eligibility','criteria'):substantive.add(citation.policy_id)
        if review.decision in ('reuse_existing','adapt_existing') and (not review.policy_ids or not set(review.policy_ids)<=substantive):raise ValueError('substantive policy evidence required')
        checks={}
        if review.decision in ('reuse_existing','adapt_existing'):
            for pid in review.policy_ids:
                candidate=candidates[pid];policy=candidate['policy']
                if candidate.get('verification')=='caution' or any(not isinstance(policy.get(k),str) or not policy[k].strip() for k in ('support','eligibility')):raise MaterialPolicyError('material_policy_information_missing')
                if candidate.get('detail_status',candidate.get('status'))=='cached' and (result.get('coverage') or {}).get('stale',True):raise MaterialPolicyError('stale_policy_detail')
                checks[pid]=target_checks(candidate,need,task)
                if review.decision=='reuse_existing' and checks[pid]['age_coverage']!='full':raise MaterialPolicyError('material_target_coverage_gap')
        if review.decision=='reuse_existing' and review.unmet_requirements:raise ValueError('unmet requirement cannot be called sufficient')
        if review.decision=='adapt_existing' and (not review.unmet_requirements or not set(review.unmet_requirements)<=set(need.verified_gaps)):raise ValueError('adaptation needs a verified material gap')
        if review.decision=='new_design_needed' and (not review.regional_fact_ids or review.search_query not in need.queries or
                not any(s['query']==review.search_query and s['scopes']==task.scopes for s in result.get('completed_searches',[]))):raise ValueError('incomplete search or context cannot establish design need')
        if review.decision in ('adapt_existing','new_design_needed') and not review.regional_fact_ids:raise ValueError('regional context required for design')
        row.update(target_group=need.target_group,need=need.need,evidence_ids=need.evidence_ids,requirements=need.requirements)
        if need.source_bands:row.update(source_bands=need.source_bands,source_age_ranges=need.source_age_ranges)
        row['guidance']=[{k:candidates[pid]['policy'].get(k) for k in ('id','title','agency','support','eligibility','criteria','application','deadline','contact','url','scope','source_updated_at')} | {'supportConditions':candidates[pid].get('conditions'),'source_kind':candidates[pid].get('source_kind','gov24'),'target_checks':checks.get(pid)} for pid in review.policy_ids]
        row['individual_eligibility_verified']=False;row['capacity_verified']=False
        row['outreach_draft']=None
        if review.decision in ('reuse_existing','adapt_existing'):
            labels={'title':'사업명','support':'지원 내용','application':'신청 방법','deadline':'신청 기한','contact':'문의처','agency':'담당 기관'}
            lines=[f'{label}: {g[k]}' for g in row['guidance'] for k,label in labels.items() if g.get(k)]
            row['outreach_draft']={'channel_proposal':review.proposed_channel,
                'text':'\n'.join(lines+['개인 자격·접수·정원은 신청 전에 담당자에게 확인해야 합니다.']),
                'dispatch_performed':False}
        output.append(row)
    return output
