"""Inventory supplied measurement definitions before using them as denominators."""
from collections import defaultdict
from math import isfinite
from backend.tools.indicators import digest


def readiness(assessment):
    if assessment['metadata'].get('analysis_version')=='v4':
        groups=defaultdict(list)
        for row in assessment['segments']:
            groups[(row['sgg'],row['sex'],row['source_age_band'])].append(row)
        return {'version':'statistical-sources-v4','input_hash':assessment['metadata']['input_hash'],
                'cohorts':[{'id':digest(key),'sgg':key[0],'sex':key[1],'source_age_band':key[2],
                            'segments':len(rows),'observed':sum(r['assessment_status']=='assessed' for r in rows),
                            'holds':sum(r['assessment_status']=='small_population_hold' for r in rows),
                            'insufficient_evidence':sum(r['assessment_status']=='insufficient_evidence' for r in rows),
                            'monthly_points':0,'weekly_card_points':len({r['week'] for r in assessment.get('weekly_observations',[])}),
                            'period_aggregate':True,'population_context_only':True,
                            'unavailable':['continuous_index','verified_target_population','service_capacity','service_usage'],
                            'source_files':['local/segments-v4.parquet','local/seohee/card_alarm_weekly.csv']}
                           for key,rows in sorted(groups.items())],
                'external_source_added':False,'limitations':['원천 단계의 상태와 카드 관측 범위를 확인합니다. 단계는 연속 지수가 아니므로 평균·신뢰구간을 산출하지 않습니다.',
                    '주간 카드는 집단별 경보 신호이며 동별 카드 관측이나 개인 위험을 뜻하지 않습니다.',
                    '집단 인구는 복지 수혜자 분모가 아니며 서비스 수용량·이용량은 없습니다.']}
    groups=defaultdict(list)
    for row in assessment['segments']:
        key=(row['sgg'],row['sex'],row['age_group'],row['index_name'],row['source_period'],digest(row['source_bands']))
        groups[key].append(row)
    result=[]
    for key,rows in sorted(groups.items()):
        valid=[r for r in rows if r['value'] is not None and isfinite(r['value'])]
        synthetic=assessment['data_mode']=='sample' or assessment['metadata'].get('synthetic_future',False)
        population_kind='synthetic_population' if synthetic else 'telecom_monthly_average' if key[0]=='11230' else 'registered_population_context'
        population=[{'evidence_id':r.get('evidence_id') or digest(r),'dong_cd':r['dong_cd'],'value':r.get('residents'),
                     'kind':population_kind,'unit':'persons','period':r['source_period'],'eligible_denominator':False,
                     'reason':'source period/age/population definitions are not verified for welfare eligibility'}
                    for r in rows if r.get('residents') is not None]
        result.append({'id':digest(key),'sgg':key[0],'sex':key[1],'age_group':key[2],'index_name':key[3],
                       'source_period':key[4],'source_bands':rows[0]['source_bands'],'segments':len(rows),
                       'observed':len(valid),'missing':len(rows)-len(valid),'comparison_ready':len(valid)>=3,
                       'monthly_points':len({r['ym'] for r in rows if r['ym']}),
                       'population_context':population,'unavailable':['verified_target_population','service_capacity','service_usage'],
                       'source_files':sorted({r['source_file'] for r in rows}),'synthetic':synthetic})
    return {'version':'statistical-sources-1','input_hash':assessment['metadata']['input_hash'],'cohorts':result,
            'external_source_added':False,'limitations':['기존 제공 자료의 정의·관측 범위를 점검한 결과입니다. 새로운 공공 통계 수집 완료가 아닙니다.',
            '서울 통신 월평균 인구와 춘천 주민 문맥은 동일 모집단이 아니며 합산·수혜 인원 추정에 사용하지 않습니다.',
            '기간 집계를 월별 관측으로 복제하지 않으며 수용량·이용량이 없으면 서비스 부족 인원을 계산하지 않습니다.']}
