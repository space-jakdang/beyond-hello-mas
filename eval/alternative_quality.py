"""Policy draft delivery, evidence linkage and independent quality are separate."""
from statistics import mean
from pydantic import Field
from eval.quality_contracts import Contract,Reviewer
from backend.tools.indicators import digest

AXES=('grounding','feasibility','clarity','equity','evaluation_plan','distinctness')

class Rating(Contract):
    alternative_id:str
    reviewer:str
    scores:dict[str,int|None]
    reason:str=Field(min_length=1)

class Ratings(Contract):
    input_hash:str
    reviewers:list[Reviewer]
    ratings:list[Rating]


def quality(sets,ratings=None):
    input_hash=digest(sets)
    refs=Ratings.model_validate(ratings or {'input_hash':input_hash,'reviewers':[],'ratings':[]})
    if refs.input_hash!=input_hash:raise ValueError('ratings refer to another proposal or review revision')
    reviewers={r.id:r for r in refs.reviewers};items={a['id']:a for s in sets for a in s['alternatives']}
    if len(reviewers)!=len(refs.reviewers) or len(items)!=sum(len(s['alternatives']) for s in sets):raise ValueError('duplicate reviewer or alternative')
    grouped={};seen=set()
    for rating in refs.ratings:
        if rating.alternative_id not in items or rating.reviewer not in reviewers:raise ValueError('unknown rating target')
        if set(rating.scores)!=set(AXES) or any(v is not None and (type(v) is not int or not 1<=v<=5) for v in rating.scores.values()):raise ValueError('six axes require integer1..5 or null')
        key=(rating.alternative_id,rating.reviewer)
        if key in seen:raise ValueError('duplicate rating')
        seen.add(key)
        if not reviewers[rating.reviewer].development_participant:grouped.setdefault(rating.alternative_id,[]).append(rating)
    rows=[]
    for body in sets:
        sources={s['policy_id']:s for s in body['evidence']['sources']}
        facts={f['evidence_id']:f for f in body['evidence']['facts']}
        for a in body['alternatives']:
            linked=bool(a['problem_evidence_ids']) and all(identifier in facts for identifier in a['problem_evidence_ids'])
            citations=all(c['policy_id'] in sources and c['evidence']==sources[c['policy_id']]['evidence'] for c in a['citations']) if a['citations'] else None
            rubric={}
            for axis in AXES:
                values=[r.scores[axis] for r in grouped.get(a['id'],[]) if r.scores[axis] is not None]
                disagreement=len(values)>=2 and max(values)-min(values)>=2
                rubric[axis]={'state':'disagreement' if disagreement else 'evaluated' if len(values)>=2 else 'not_evaluated','value':mean(values) if len(values)>=2 and not disagreement else None,'independent_count':len(values)}
            rows.append({'alternative_id':a['id'],'title':a['title'],'owner_id':body['owner_id'],'dong_cd':body['dong_cd'],'dong_nm':body['dong_nm'],
                'version':body['version'],'revision':body['review_revision'],'generation_mode':a['generation_mode'],'evidence_status':a['evidence_status'],
                'regional_link_valid':linked,'citation_match':citations,'grounding_eligible':a['generation_mode']=='llm' and a['evidence_status']!='concept_only' and linked,
                'rubric':rubric,'field_effectiveness':None})
    return {'input_hash':input_hash,'sets':len(sets),'exactly_three':sum(len(s['alternatives'])==3 for s in sets),'alternatives':len(rows),
        'strategy_unique_sets':sum(len({a['strategy'] for a in s['alternatives']})==3 for s in sets),
        'template_count':sum(r['generation_mode']=='template_fallback' for r in rows),'fixture_count':sum(r['generation_mode']=='fixture' for r in rows),
        'grounding_eligible':sum(r['grounding_eligible'] for r in rows),'rows':rows,
        'limitations':['세 개 생성·전략 이름 차이는 적합성이나 실질적 다양성 점수가 아닙니다.','동일 원문 인용은 참조 연결 검사이며 사실성·효과 검증이 아닙니다.',
            '각 축 독립 검토자 2명 미만은 미평가, 2점 이상 차이는 불일치입니다. 독립성은 제출한 검토자 정보 기준입니다.',
            '구상안·테스트 작성은 RAGAS 근거 평가 대상에서 제외합니다. 실제 정책 효과·타 지역 일반화는 별도 검증이 필요합니다.']}
