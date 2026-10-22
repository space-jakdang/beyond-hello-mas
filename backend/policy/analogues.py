"""Official policy examples for adaptation, never local eligibility decisions."""
from pydantic import Field
from backend.policy.design_contracts import Contract,Analogue
from backend.policy.service import Scope,SCOPES,Search,LIMITATION


class AnalogueRequest(Contract):
    local_scope:Scope
    query:str=Field(min_length=1,max_length=200)
    target_group:str=Field(min_length=1,max_length=200)


def research(service,request):
    request=AnalogueRequest.model_validate(request)
    scopes=[scope for scope in SCOPES if scope!=request.local_scope]
    found=service.search(Search(scopes=scopes,query=request.query,per_page=100))
    coverage=found['coverage'];sources=[];checks=[]
    target_terms=[word for word in ('청년','청소년','중년','장년','노년','노인') if word in request.target_group]
    def relevance(p):
        text=lambda field:str(p.get(field) or '').casefold()
        query=request.query.casefold()
        return (4*(query in text('title'))+2*(query in text('summary'))+
                sum(4*(word in text('title'))+2*(word in text('eligibility')) for word in target_terms))
    candidates=sorted(found['items'],key=lambda p:(-relevance(p),p['id']))[:5]
    for candidate in candidates:
        detail=service.detail(candidate['id']);p=detail.get('policy')
        usable=bool(detail['status']=='live' and p and p.get('url') and detail.get('checked_at') and p['scope'] in scopes)
        reason=('detail_not_live' if detail['status']!='live' else 'missing_policy' if not p else 'missing_source_url' if not p.get('url') else 'missing_checked_at' if not detail.get('checked_at') else 'scope_mismatch' if p['scope'] not in scopes else None)
        checks.append({'policy_id':candidate['id'],'status':detail['status'],'usable':usable,'reason':reason})
        if not usable:continue
        analogue=Analogue(policy_id=p['id'],title=p['title'],scope=p['scope'],source_url=p['url'],checked_at=detail['checked_at'],
            fields={k:p[k] for k in ('title','support','eligibility','criteria','deadline') if p.get(k)})
        sources.append({'source':analogue.model_dump(),
            'comparison':{'search_term':request.query,'requested_target_group':request.target_group,
                'similarity_basis':'keyword_rank_only','target_group_fit':'not_established','demographic_similarity':'not_established',
                'differences':[f"원 정책 관할 {p['scope']} / 제안 대상 관할 {request.local_scope}",
                    '인구 구성·전달기관·예산·수용량의 동등성 미확인'],
                'adaptation_checks':['원문 대상 조건과 지역 대상집단 비교','현지 운영기관·수용량·예산·법적 근거 확인']}})
    fresh=bool(coverage.get('source_complete') and not coverage.get('stale') and (coverage.get('last_attempt') or {}).get('status')=='success')
    return {'status':'evidence_available' if sources and fresh else 'needs_evidence',
        'request':request.model_dump(),'search_scopes':scopes,'query':request.query,
        'search_exhausted':found['next_page'] is None,'representative_sample':False,'absence_established':False,
        'candidate_window':100,'candidates_considered':len(found['items']),'selection_basis':'title_summary_target_keyword_rank_not_eligibility_verification','total_matches':found['total'],'next_page':found['next_page'],'coverage':coverage,
        'analogues':sources,'detail_checks':checks,'local_eligibility':'not_established',
        'all_policies_known':False,'allocation_performed':False,
        'limitations':[LIMITATION,'최대 100건의 검색 일치 결과 중 제목·요약·대상 단어를 우선하여 상세 5건을 조회합니다. 전문 검색이나 자격 검증이 아닙니다.',
            '최대 5건의 검색어 일치 참고 사례이며 인구·지역 특성의 유사성을 검증한 결과가 아닙니다.',
            '지원하는 중앙·서울·강남·강원·춘천 관할 내 사례만 조회하며 그 밖의 지역은 포함하지 않습니다.']}
