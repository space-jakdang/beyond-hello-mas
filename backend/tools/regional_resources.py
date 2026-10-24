"""Provisional evidence-to-need mapping plus existing strict catalog filters."""
import re
from math import isfinite
from backend.tools.matching import MatchRequest, map_intensity, match

MAPPING_VERSION='regional-needs-2'


def source_age_ranges(bands):
    parsed=[]
    for values in bands.values():
        for value in values:
            v=value.replace('–','-').replace('~','-')
            if re.fullmatch(r'\d{2}s',v):low=int(v[:2]);high=low+9
            elif re.fullmatch(r'\d{2}(plus|\+)',v):low=int(v[:2]);high=120
            elif re.fullmatch(r'\d{1,3}-\d{1,3}',v):low,high=map(int,v.split('-'))
            else:return None
            if not 0<=low<=high<=120:return None
            parsed.append((low,high))
    merged=[]
    for low,high in sorted(parsed):
        if merged and low<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(high,merged[-1][1]))
        else:merged.append((low,high))
    return merged or None


def source_ages(bands):
    ranges=source_age_ranges(bands)
    return (ranges[0][0],ranges[-1][1]) if ranges else None


def need_profile(row):
    valid=lambda value:type(value) in (float,int) and isfinite(value)
    observed=valid(row.get('value'))
    components={key:value for key,value in (row.get('components') or {}).items() if valid(value)}
    factors={key:value for key,value in components.items() if key!='youth_population_both_sexes'}
    proxy=observed and row['index_name'] in ('S1','v3')
    return {'mapping_version':MAPPING_VERSION,'needs':['relationship'] if proxy else [],
        'need_basis':'index_proxy_only' if proxy else 'insufficient_evidence',
        'mapping_status':'index_hypothesis' if proxy else 'unmapped_evidence' if observed else 'insufficient_observation',
        'observed_factors':factors,
        'population_context':{key:value for key,value in components.items() if key=='youth_population_both_sexes'},
        'invalid_factors':sorted(set(row.get('components') or {})-set(components)),
        'needed_data':(['관계 지원 필요와 접근 경로의 현장 확인'] if proxy else
                       ['원천 요인 정의·욕구별 측정 자료','현장 욕구 확인'] if observed else ['누락된 원천 지수·기간 확인'])+
                      ['대상 인구 분모','기존 서비스 이용·수용량'],
        'next_action':'관계 지원 필요를 확인한 뒤 조건부 후보를 검토합니다.' if proxy else
                      '요인 정의와 현장 욕구를 확인한 뒤 자원을 다시 조회합니다.' if observed else '원천 관측을 보완한 뒤 다시 분석합니다.'}


def needs_for(row):
    return need_profile(row)['needs']


def candidates(assessment,statistics,resources):
    rows=[]
    blocked=set(statistics.get('blocked_evidence_ids',[]))
    profiles={p['evidence_id']:p for p in statistics.get('summary',{}).get('policy_needs',{}).get('profiles',[])}
    insights={i['evidence_id']:i for i in statistics.get('summary',{}).get('insights',{}).get('items',[])}
    for row in assessment['segments']:
        base={k:row[k] for k in ('evidence_id','dong_cd','dong_nm','sgg','sex','age_group','stage','source_bands')}
        profile=need_profile(row);needs=profile['needs'];ranges=source_age_ranges(row['source_bands']);ages=(ranges[0][0],ranges[-1][1]) if ranges else None
        reason=('statistics_unreviewed' if statistics.get('status')!='reviewed' else
                'insufficient_observation' if row['stage'] is None or row['evidence_id'] in blocked else
                'unknown_source_age' if ages is None else 'unmapped_evidence' if not needs else None)
        filtered=reason is None
        result={'recommendations':[],'excluded':[],'shortfall':3,'uncovered_needs':needs}
        if reason is None:
            request=MatchRequest(sgg=row['sgg'],age_min=ages[0],age_max=ages[1],needs=needs,stage=row['stage'],
                intensity=map_intensity(row['stage']),as_of=assessment['task']['as_of'])
            result=match(resources,request,regional_ages=ranges)
            if not result['recommendations']:reason='no_eligible_catalog_candidates'
        evidence={'version':'resource-decision-2', 'decision_contract_version':'regional-decision-2', 'observation':{k:row.get(k) for k in
                    ('evidence_id','index_name','value','source_period','components','source_bands')},
                  'mapping_version':MAPPING_VERSION,'need_profile':profile,'provisional_needs':needs,'statistical_context':({**profiles.get(row['evidence_id'],{}),'insight':insights.get(row['evidence_id'])}),
                  'filter_request':request.model_dump(mode='json') if filtered else None,
                  'catalog_metadata':result.get('metadata'),
                  'presented_candidates':[{'id':c['id'],'name':c['name'],'needs':c['needs'],
                      'source_url':c.get('source_url'),'collected_at':c.get('collected_at'),
                      'eligibility':c['eligibility'],'valid_until':c.get('valid_until'),
                      **{k:c[k] for k in ('candidate_status','condition_checks','unknown_conditions','age_coverage','eligible_age_ranges','rank_factors')}} for c in result['recommendations']],
                  'unknown_conditions':['individual_eligibility','application_acceptance','remaining_capacity'],
                  'model_reason':None}
        rows.append({**base,**result,'decision_contract_version':'regional-decision-2','decision_evidence':evidence,
                     'needs':needs,'age_range':ages,'source_age_ranges':ranges,'reason':reason,
                     'statistical_context':({**profiles.get(row['evidence_id'],{}),'insight':insights.get(row['evidence_id'])}),'catalog_filter_performed':filtered,'status':'candidate' if result['recommendations'] else 'needs_human',
                     'mapping_version':MAPPING_VERSION,'need_profile':profile,'provisional':True,'remaining_capacity':None,
                     'allocation_performed':False,'as_of':assessment['task']['as_of']})
    return rows


def select_candidates(rows):
    reason='욕구 가설 일치 수 내림차순, 미확인 조건 수 오름차순, 동률 자원 ID 순의 검토 후보입니다.'
    selected=[]
    for row in rows:
        evidence={**row['decision_evidence'],'matching_mode':'deterministic-regional-1',
                  'selection_reason':reason if row['recommendations'] else '등록 조건 검사 후 제안할 후보가 없습니다.' if row.get('catalog_filter_performed') else '관측 또는 통계 검토가 부족해 자원 순위를 계산하지 않았습니다.','model_reason':None}
        selected.append({**row,'matching_mode':'deterministic-regional-1','decision_evidence':evidence,
                         'status':'conditional_recommendation' if row['recommendations'] else 'needs_human'})
    return selected,{'matching_mode':'deterministic-regional-1','model_calls':0,
        'status':'reviewed' if any(row['recommendations'] for row in selected) else 'needs_human',
        'summary':(reason if any(row['recommendations'] for row in selected) else '제안할 후보가 없어 보류 사유와 추가 확인 계획을 검토해야 합니다.')+' 실제 자격·접수·정원은 담당자가 확인해야 합니다.'}


def policy_gap(row,explicit=False,research=None):
    needs=row.get('needs',[]);uncovered=row.get('uncovered_needs',needs)
    unknown=any(c.get('unknown_conditions') for c in row.get('recommendations',[]))
    if row.get('stage') is None or row.get('reason')=='insufficient_observation':
        status='insufficient_observation';needed=False;action='원천 관측을 보완한 뒤 필요를 확인합니다.'
    elif not needs:
        status='needs_unconfirmed';needed=False;action='욕구별 측정 자료와 현장 필요를 확인합니다.'
    elif row.get('reason')=='matching_unavailable' or not row.get('catalog_filter_performed'):
        status='matching_incomplete';needed=False;action='통계 검토 또는 카탈로그 조회를 완료합니다.'
    elif uncovered:
        status='unmet_need_hypotheses' if row.get('recommendations') else 'no_catalog_candidates'
        needed=True;action='미충족 필요 가설을 대상으로 범위를 정해 정책을 조사합니다.'
    elif unknown:
        status='qualification_unconfirmed';needed=False;action='후보의 개인 자격·해당 연령·지원 조건을 확인합니다.'
    else:
        status='candidate_coverage';needed=False;action='후보의 접수 여부와 실제 수용량을 확인합니다.'
    reasons=([status] if needed else [])+(['explicit_request'] if explicit else [])
    search='not_requested';count=None
    if research is not None:
        count=len(research.get('candidates',research.get('recommendations',[])))
        search=('search_failed' if research.get('status') in ('failed','error','unavailable','tool_error','tool_unavailable') else
                'search_incomplete' if research.get('search_complete_within_scope') is not True else
                'candidates_found' if count else 'no_verified_candidates_within_scope')
        action='조회된 후보의 원문·대상 조건을 확인합니다.' if count else '검색 범위·실패·한도 사유를 확인하고 현장 자료를 보완합니다.'
    return {'version':'policy-gap-1','status':status,'research_needed':needed or explicit,'research_reasons':reasons,
            'recommendation_slot_shortfall':row.get('shortfall',3),'unmet_need_hypotheses':uncovered,
            'qualification_unconfirmed':unknown,'search_status':search,'policy_candidates_returned':count,'search_scope':research.get('search_scope') if research else None,
            'field_gap_status':'not_evaluated','absence_established':False,'next_action':action}
