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
                      **{k:c[k] for k in ('candidate_status','condition_checks','unknown_conditions','age_coverage','eligible_age_ranges')}} for c in result['recommendations']],
                  'unknown_conditions':['individual_eligibility','application_acceptance','remaining_capacity'],
                  'model_reason':None}
        rows.append({**base,**result,'decision_contract_version':'regional-decision-2','decision_evidence':evidence,
                     'needs':needs,'age_range':ages,'source_age_ranges':ranges,'reason':reason,
                     'statistical_context':({**profiles.get(row['evidence_id'],{}),'insight':insights.get(row['evidence_id'])}),'catalog_filter_performed':filtered,'status':'candidate' if result['recommendations'] else 'needs_human',
                     'mapping_version':MAPPING_VERSION,'need_profile':profile,'provisional':True,'remaining_capacity':None,
                     'allocation_performed':False,'as_of':assessment['task']['as_of']})
    return rows
