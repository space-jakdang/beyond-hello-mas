"""Decision-oriented comparisons; effects and needs remain hypotheses."""
from statistics import median
from math import isfinite
from backend.tools.indicators import digest


def cohort(row):
    return (row['sgg'],row['sex'],row['age_group'],row['index_name'],row['source_period'],digest(row['source_bands']))


def insights(assessment):
    source=assessment.get('source_observations',assessment['segments'])
    items=[]
    for row in assessment['segments']:
        peers=[r for r in source if r.get('preferred',True) and r['dong_cd']!=row['dong_cd'] and cohort(r)==cohort(row)
               and r.get('ym')==row.get('ym') and r['value'] is not None and isfinite(r['value'])]
        value=row['value'];valid=value is not None and isfinite(value)
        center=median(r['value'] for r in peers) if len(peers)>=3 else None
        direction=-1 if row.get('risk_direction')=='low_is_risk' else 1
        difference=direction*(value-center) if valid and center is not None else None
        measured={k:v for k,v in row.get('components',{}).items() if k in ('relationship','economic','housing','employment','health','emotional','activity_deficit') and type(v) in (float,int) and isfinite(v)}
        # Magnitudes across different factor scales are not comparable contribution weights.
        positive=sorted(k for k,v in measured.items() if v>0)
        flags=row.get('flags',[])
        action='추가 비교 자료를 확보한 뒤 지원 우선순위를 검토합니다.' if difference is None else '비교군보다 위험 방향으로 치우쳐 우선 현장 확인과 접근 경로를 검토합니다.' if difference>0 else '비교군보다 두드러진 위험 차이가 없어 보편적 안내와 관측 유지를 검토합니다.'
        items.append({'evidence_id':row['evidence_id'],'dong_nm':row['dong_nm'],'question':'비교 가능한 다른 동과 어떤 차이가 있는가?',
                      'comparison':{'peer_count':len(peers),'peer_median':center,'risk_direction_difference':difference,'unit':'source_index',
                                    'source_period':row['source_period'],'source_bands':row['source_bands']},
                      'measured_need_signals':positive,'need_interpretation':'observed_factor_hypotheses' if measured else 'index_proxy_only',
                      'policy_implication':action,'missing_evidence':['서비스 실제 이용량·수용량','수급 대상 인구 분모'],
                      'limitations':['차이는 인과 효과나 위험 확률이 아닙니다.']+(['성별로 측정된 지수가 아니므로 성별 차이로 해석하지 않습니다.'] if 'index_not_sex_specific' in flags else [])})
    return {'version':'policy-insights-1','items':items,'input_hash':assessment['metadata']['input_hash'],'causal_claim':False}


def persistence(observation):
    result=[]
    for series in observation.get('series',[]):
        points=series['points'];recent=points[-3:]
        changes=[p['change'] for p in recent[1:] if p.get('change') is not None]
        direction='increasing' if len(recent)==3 and len(changes)==2 and all(c>0 for c in changes) else 'decreasing' if len(recent)==3 and len(changes)==2 and all(c<0 for c in changes) else 'mixed_or_flat' if len(recent)==3 and len(changes)==2 else 'unavailable'
        result.append({'cohort_id':series['cohort_id'],'direction':direction,'periods':[p['ym'] for p in recent],
                       'interpretation':'최근 연속 3개 관측의 방향이며 계절 조정·미래 예측·인과 효과가 아닙니다.'})
    return result
