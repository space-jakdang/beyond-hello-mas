"""Policy draft delivery, evidence linkage and independent quality are separate."""
from statistics import mean
import json
import random
from pathlib import Path
from uuid import uuid4
from pydantic import Field
from eval.quality_contracts import Contract,Reviewer
from backend.tools.indicators import digest

AXES=('grounding','feasibility','clarity','equity','evaluation_plan','distinctness')


def packet(pairs):
    """Prepare private, paired set-level review, including useful zero-draft results."""
    if not isinstance(pairs,list) or not pairs:raise ValueError('provide nonempty paired policy sets')
    identifiers=[p['case_id'] for p in pairs]
    if any(not isinstance(i,str) or not i.strip() for i in identifiers) or len(set(identifiers))!=len(identifiers):raise ValueError('unique case IDs required')
    fields=('evidence_id','target_group','stage','base_stage','value','source_bands','source_period',
            'methodology_version','source_age_band','assessment_status','card_week','card_evidence')
    selection=('sgg','ym','as_of','target_groups','selected_week','synthetic_future')
    from backend.policy.alternative_export import response_reason
    items=[];mapping={}
    for index,pair in enumerate(pairs):
        before,after=pair['baseline'],pair['current']
        for body in (before,after):quality([body])
        if before['dong_cd']!=after['dong_cd'] or before['data_mode']!=after['data_mode'] or any(before['scope'].get(k)!=after['scope'].get(k) for k in selection):
            raise ValueError('paired outputs require the same frozen selection and data mode')
        problem=lambda body:sorted(({k:f.get(k) for k in fields} for f in body['evidence']['facts']),key=lambda f:f['evidence_id'])
        if problem(before)!=problem(after):raise ValueError('paired outputs require identical problem observations')
        profile=after['evidence'].get('regional_profile')
        if profile and any(profile['request'].get(k)!=v for k,v in {'sgg':after['scope']['sgg'],'dong_cd':after['dong_cd'],'as_of':after['scope']['as_of']}.items()):
            raise ValueError('regional profile differs from paired selection')
        for arm,body in (('baseline',before),('current',after)):
            identifier=str(uuid4())
            mapping[identifier]={'case_id':pair['case_id'],'arm':arm,'index':index,'owner_id':body['owner_id'],'version':body['version'],'revision':body['review_revision']}
            alternatives=[{k:v for k,v in a.items() if k not in ('id','strategy','generation_mode','evidence_status','review_status','review','operator_notes')} for a in body['alternatives']]
            items.append({'blind_id':identifier,'case':'case-'+str(index+1),'data_mode':body['data_mode'],
                'problem_observations':problem(body),'regional_facts':profile['facts'] if profile else [],
                'policy_sources':body['evidence']['sources'],
                'output':{'status':{'reuse_existing':'기존 정책 활용·안내','draft':'보완·신규 대안 검토','needs_evidence':'추가 근거 확인 필요'}.get(body.get('status'),'정책 대안 검토'),
                          'hold_reason':response_reason(body['fallback_reason']) if body.get('fallback_reason') else None,
                          'response_decisions':body.get('response_decisions',[]),'alternatives':alternatives,
                          'missing_groups':body.get('missing_groups',[]),'limitations':body['evidence'].get('limits',[])}})
    random.SystemRandom().shuffle(items)
    fixture=json.loads((Path(__file__).parent/'fixtures/pinpoint-policy-cases.json').read_text())
    result={'schema_version':'pinpoint-review-packet-1','input_hash':digest(pairs),'rubric_version':fixture['version'],
        'rubric':fixture['rubric'],'items':items,'independent_quality':None,
        'rating_scale':{'1':'근거가 없거나 잘못 연결됨','2':'일부 연결되지만 중요한 결함이 있음','3':'기본 요건을 충족하나 추가 확인이 필요함','4':'구체적 근거와 운영 선택이 대부분 연결됨','5':'제공된 근거 안에서 구체적이고 검증 가능한 설명을 충족함'},
        'rating_instructions':'각 기준에 1–5와 근거를 기록하세요. 적용 불가는 null과 사유를 남기세요. 0안의 다양성은 적용 불가이며 활용·보류 판단 자체를 나머지 기준으로 평가합니다. 개발 비참여 검토자 2명 이상이 독립 평정하기 전 집계하지 않습니다.',
        'limitations':['방식·실행 ID와 순서를 가렸지만 문구·출처로 방식이나 지역을 추측할 수 있습니다.',
            '두 방식에 같은 지역 문맥을 제공하며 출력 전체(활용·보류·대안)를 평가합니다. 대안 0개는 품질 0점이 아닙니다.',
            '독립 평정 전 점수는 N/A입니다. 이 여섯 기준은 기존 대안별 평정 API의 축과 다른 버전이며 자동 업로드하지 않습니다.']}
    private_map={'schema_version':result['schema_version'],'input_hash':result['input_hash'],'packet_hash':digest(result),'mapping':mapping}
    template={'input_hash':result['input_hash'],'packet_hash':private_map['packet_hash'],'rubric_version':result['rubric_version'],
        'reviewers':[],'ratings':[{'blind_id':item['blind_id'],'reviewer':None,'scores':{axis:None for axis in result['rubric']},'reason':None} for item in items]}
    return result,private_map,template

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
            linked=bool(a['problem_evidence_ids']) and all(identifier in facts and facts[identifier].get('usable_for_design',True) for identifier in a['problem_evidence_ids'])
            citations=all(c['policy_id'] in sources and c['evidence']==sources[c['policy_id']]['evidence'] for c in a['citations']) if a['citations'] else None
            context_link=None
            if body.get('proposal_version')=='regional-policy-2':
                regional={f['fact_id'] for f in (body['evidence'].get('regional_profile') or {}).get('facts',[]) if f['status']=='observed'}
                context_link=bool(a.get('context_links')) and all(link['fact_id'] in regional for link in a['context_links'])
                normalize=lambda value:value.replace('\r\n','\n').replace('\r','\n')
                elements=a.get('source_elements',[])
                exact=bool(elements) and all(isinstance(sources.get(c['policy_id'],{}).get('fields',{}).get(c['field']),str) and normalize(c['quote']) in normalize(sources[c['policy_id']]['fields'][c['field']]) for c in elements)
                citations=bool(citations and exact)
            rubric={}
            for axis in AXES:
                values=[r.scores[axis] for r in grouped.get(a['id'],[]) if r.scores[axis] is not None]
                disagreement=len(values)>=2 and max(values)-min(values)>=2
                rubric[axis]={'state':'disagreement' if disagreement else 'evaluated' if len(values)>=2 else 'not_evaluated','value':mean(values) if len(values)>=2 and not disagreement else None,'independent_count':len(values)}
            rows.append({'alternative_id':a['id'],'title':a['title'],'owner_id':body['owner_id'],'dong_cd':body['dong_cd'],'dong_nm':body['dong_nm'],
                'version':body['version'],'revision':body['review_revision'],'generation_mode':a['generation_mode'],'evidence_status':a['evidence_status'],
                'regional_link_valid':linked,'context_link_valid':context_link,'citation_match':citations,'grounding_eligible':a['generation_mode']=='llm' and a['evidence_status']!='concept_only' and linked and (context_link is None or context_link and citations is True),
                'rubric':rubric,'field_effectiveness':None})
    conditional=[s for s in sets if s.get('proposal_version')=='regional-policy-2']
    requested=len(sets)-len(conditional)+sum(any(r['decision'] in ('adapt_existing','new_design_needed') for r in s.get('response_decisions',[])) for s in conditional)
    contract_pass=sum((s['status']=='draft' and len(s['alternatives'])==3 and len({a['proposed_service'].strip().casefold() for a in s['alternatives']})==3 and len({a.get('delivery_model','').strip().casefold() for a in s['alternatives']})==3 and all(r['context_link_valid'] and r['regional_link_valid'] and r['citation_match'] for r in rows if r['owner_id']==s['owner_id'] and r['dong_cd']==s['dong_cd'])) or (s['status'] in ('reuse_existing','needs_evidence') and not s['alternatives']) for s in conditional)
    return {'conditional_sets':len(conditional),'design_requested_sets':requested,'reuse_sets':sum(s['status']=='reuse_existing' for s in conditional),
        'evidence_hold_sets':sum(s['status']=='needs_evidence' for s in conditional),'conditional_contract_pass_sets':contract_pass,'input_hash':input_hash,'sets':len(sets),'exactly_three':sum(len(s['alternatives'])==3 for s in sets),'alternatives':len(rows),
        'strategy_unique_sets':sum(len({a['strategy'] for a in s['alternatives']})==3 for s in sets),
        'template_count':sum(r['generation_mode']=='template_fallback' for r in rows),'fixture_count':sum(r['generation_mode']=='fixture' for r in rows),
        'grounding_eligible':sum(r['grounding_eligible'] for r in rows),'rows':rows,
        'limitations':['세 개 생성·전략 이름 차이는 적합성이나 실질적 다양성 점수가 아닙니다.','동일 원문 인용은 참조 연결 검사이며 사실성·효과 검증이 아닙니다.',
            '각 축 독립 검토자 2명 미만은 미평가, 2점 이상 차이는 불일치입니다. 독립성은 제출한 검토자 정보 기준입니다.',
            '구상안·테스트 작성은 RAGAS 근거 평가 대상에서 제외합니다. 실제 정책 효과·타 지역 일반화는 별도 검증이 필요합니다.']}


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Prepare a private paired policy review packet; no model calls.')
    parser.add_argument('pairs',type=Path,help='JSON list of case_id, baseline and current stored sets')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:review,private_map,template=packet(json.loads(args.pairs.read_text()))
    except (OSError,ValueError,KeyError,TypeError) as exc:parser.error(str(exc))
    args.output.mkdir(parents=True,exist_ok=False)
    for name,body in (('review-packet',review),('private-key',private_map),('ratings-template',template)):
        (args.output/(name+'.json')).write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n')
    print(args.output)


if __name__=='__main__':main()
