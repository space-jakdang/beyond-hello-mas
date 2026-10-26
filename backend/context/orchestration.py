"""Owner-scoped immutable profiles shared by every requested cohort."""
import json
from backend.context.contracts import ContextRequest
from backend.context.service import ContextService,ContextUnavailable
import time
from backend.tools.indicators import digest

VERSION='regional-policy-2'


def freeze(service,owner,task,dongs,deadline=None):
    year=min(service.settings.regional_reference_year,int(task['as_of'][:4]))
    def checked(profiles):
        from backend.regional_batch import BatchConflict
        if dongs and set(profiles)!={d['dong_cd'] for d in dongs}:raise BatchConflict('owner context scope differs')
        for code,profile in profiles.items():
            request=ContextRequest.model_validate(profile['request'])
            if (request.sgg,request.dong_cd,request.as_of.isoformat(),profile['data_mode'])!=(task['sgg'],code,task['as_of'],service.settings.data_mode):
                raise BatchConflict('owner context scope or data mode differs')
        return profiles
    with service.store.connection() as db:
        row=db.execute('SELECT body FROM regional_context_snapshots WHERE owner_id=?',(owner,)).fetchone()
    if row:return checked(json.loads(row[0]))
    memo={}
    def fetch(endpoint,args):
        if deadline is not None and time.time()>=deadline:raise ContextUnavailable('workflow_deadline')
        key=digest([endpoint,args])
        if key not in memo:
            try:memo[key]=(source.request(endpoint,args),None)
            except Exception as exc:memo[key]=(None,exc)
        result,error=memo[key]
        if error:raise error
        return result
    source=ContextService(service.settings,fetch);profiles={}
    for dong in dongs:
        request=ContextRequest(sgg=task['sgg'],dong_cd=dong['dong_cd'],reference_year=year,as_of=task['as_of'])
        profiles[dong['dong_cd']]=source.profile(request)
    with service.store.connection(write=True) as db:
        db.execute('INSERT OR IGNORE INTO regional_context_snapshots VALUES (?,?)',(owner,json.dumps(profiles,ensure_ascii=False)))
        return checked(json.loads(db.execute('SELECT body FROM regional_context_snapshots WHERE owner_id=?',(owner,)).fetchone()[0]))


def age_coverage_gaps(row,need):
    candidates=[r for r in row['recommendations'] if need in r.get('needs',[])]
    if not candidates or not row.get('source_age_ranges') or any('eligible_age_ranges' not in r for r in candidates):return []
    observed=row['source_age_ranges']
    covered=sorted(interval for r in candidates for interval in r.get('eligible_age_ranges',[]))
    missing=[]
    for low,high in observed:
        cursor=low
        for start,end in covered:
            if end<cursor:continue
            if start>high:break
            if start>cursor:missing.append([cursor,start-1])
            cursor=max(cursor,end+1)
            if cursor>high:break
        if cursor<=high:missing.append([cursor,high])
    return ['검토 후보가 요청 집단과 겹치는 관측 연령대 일부를 포함하지 않습니다: '+', '.join(str(low)+'–'+str(high)+'세' for low,high in missing)] if missing else []


def research_need(proposal,row,need):
    from backend.policy.research_contracts import ResearchNeed
    from backend.tools.regional_resources import source_age_ranges
    bands=row.get('source_bands',{})
    group=proposal['task']['sex']+'/'+proposal['task'].get('source_age_band',proposal['task']['age_group'])
    return ResearchNeed(need_id=row['evidence_id']+':'+need,target_group=group,need=need,
        evidence_ids=[row['evidence_id']],requirements=['공식 제공 내용이 '+need+' 조사 가설에 대응하는지 확인'],
        source_bands=bands,source_age_ranges=source_age_ranges(bands) or [],verified_gaps=age_coverage_gaps(row,need),
        queries=[{'relationship':'고립','emotional':'상담','economic':'경제','housing':'주거','employment':'일자리','health':'건강'}.get(need,need)])


def research_task(proposal,task):
    profiles=proposal['assessment'].get('regional_context',{})
    priority=set((proposal['workflow'].get('analysis') or {}).get('priority_evidence_ids',[]))
    selected=[r for r in proposal['assignments'] if r['evidence_id'] in priority][:1]
    needs=[];resources={};codes=set()
    for row in selected:
        codes.add(row['dong_cd'])
        for need in row.get('needs',[]):
            needs.append(research_need(proposal,row,need).model_dump())
        for resource in row['recommendations']:resources[resource['id']]=resource
    task.update(research_version='regional-research-2',needs=needs[:8],regional_profiles=[profiles[c] for c in sorted(codes) if c in profiles],
                statistical_notes=proposal['workflow'].get('statistics',{}).get('regional_notes',[]),existing_resources=list(resources.values())[:15])
    return task


def complete_reviews(proposal,result,task):
    from backend.policy.research_contracts import evidence_hold
    reviews=list(result.get('need_reviews',[]));known={r['need_id'] for r in reviews}
    for row in proposal['assignments']:
        for need in row.get('needs') or ['unconfirmed']:
            identifier=row['evidence_id']+':'+need
            if identifier in known:continue
            reason='need_not_established' if need=='unconfirmed' else result['status'] if result['status'] in ('budget_exhausted','model_unavailable_or_budget','context_input_limit','invalid_evidence','step_limit','search_incomplete','call_limit','deadline') else 'research_budget_scope_or_unavailable'
            reviews.append(evidence_hold(research_need(proposal,row,need),reason))
    return reviews
