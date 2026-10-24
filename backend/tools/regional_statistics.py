"""Descriptive evidence only: no invented time points or cross-region scores."""
from collections import Counter
from math import isfinite
from statistics import mean, median
from backend.tools.indicators import digest
from backend.tools.segments_v3 import load_segments


def summary(assessment):
    from backend.tools.statistical_sources import readiness
    from backend.tools.policy_insights import insights
    rows=assessment['segments']
    valid=[r for r in rows if r['value'] is not None and isfinite(r['value']) and r['stage'] is not None]
    groups={}
    for row in valid:
        # Never combine distinct scales, populations or source periods.
        key=(row['sgg'],row['sex'],row['age_group'],row['index_name'],row['source_period'],digest(row['source_bands']))
        groups.setdefault(key,[]).append(row['value'])
    distributions=[{'sgg':key[0],'sex':key[1],'age_group':key[2],'index_name':key[3],
                    'source_period':key[4],'source_bands_hash':key[5],'scope':'within-selected-district-group','n':len(values),'mean':mean(values),'median':median(values),
                    'min':min(values),'max':max(values)} for key,values in sorted(groups.items())]
    blocked=[r['evidence_id'] for r in rows if r not in valid]
    return {'tool':'summary','tool_version':'regional-statistics-1','total':len(rows),'observed':len(valid),
            'missing':len(blocked),'missing_rate':len(blocked)/len(rows) if rows else None,
            'stage_counts':dict(sorted(Counter(str(r['stage']) for r in valid).items())),
            'distributions':distributions,'blocked_evidence_ids':blocked,
            'input_hash':assessment['metadata']['input_hash'],'causal_claim':False,'data_readiness':readiness(assessment),'insights':insights(assessment),
            'confidence_interval':None,'cross_region_comparable':False,'policy_needs':policy_needs(assessment)}


def trend(settings,assessment):
    task=assessment['task']
    if task.get('future_id'):
        from backend.future import scenario_rows
        from backend.tools.regional_task import RegionalTask
        rows,_,_=scenario_rows(settings,RegionalTask.model_validate(task))
    elif assessment.get('source_observations') is not None:
        from backend.app.contracts import SegmentV3
        rows=[SegmentV3.model_validate(r) for r in assessment['source_observations']]
    else:
        rows,_=load_segments(settings)
    ids={(r['dong_cd'],r['sex'],r['age_group'],r['index_name']) for r in assessment['segments']}
    series={}
    for row in rows:
        key=(row.dong_cd,row.sex,row.age_group,row.index_name)
        if not row.preferred or key not in ids or row.ym is None or row.ym>task['ym']:continue
        series.setdefault(key,[]).append({'ym':row.ym,'value':row.value,'source_bands':row.source_bands})
    inputs_hash=digest([{'cohort':list(key),'points':points} for key,points in sorted(series.items())])
    result=[]
    for key,points in sorted(series.items()):
        points.sort(key=lambda p:p['ym'])
        for i,point in enumerate(points):
            previous=points[i-1] if i else None
            current_month=int(point['ym'][:4])*12+int(point['ym'][5:])
            prev_month=int(previous['ym'][:4])*12+int(previous['ym'][5:]) if previous else None
            comparable=previous and current_month-prev_month==1 and previous['source_bands']==point['source_bands']
            point['change']=point['value']-previous['value'] if comparable and point['value'] is not None and previous['value'] is not None else None
        result.append({'cohort_id':'/'.join(key),'points':points})
    return {'tool':'trend','tool_version':'regional-statistics-1','status':'available' if result else 'unavailable',
            'reason':None if result else 'no_monthly_observations','series':result,
            'data_mode':assessment['data_mode'],'input_hash':inputs_hash,'output_hash':digest(result),'forecast':False,'synthetic_future':bool(task.get('future_id'))}


def source_check(assessment):
    return {'tool':'source_check','tool_version':'regional-statistics-1','items':[
        {'evidence_id':r['evidence_id'],'source_file':r['source_file'],'source_period':r['source_period'],
         'source_bands':r['source_bands'],'flags':r.get('flags',[]),'value_missing':r['value'] is None,
         'stage_missing':r['stage'] is None,'status':'missing' if r['value'] is None or r['stage'] is None else 'synthetic_scenario' if 'synthetic_future' in r.get('flags',[]) else 'observed'} for r in assessment['segments']]}


def run_tool(name,settings,assessment):
    if name=='summary':return summary(assessment)
    if name=='trend':return trend(settings,assessment)
    if name=='source_check':return source_check(assessment)
    if name=='sensitivity':return sensitivity(assessment)
    if name=='policy_insights':
        from backend.tools.policy_insights import insights
        return {'tool':'policy_insights',**insights(assessment)}
    raise ValueError('unsupported statistics tool')


def sensitivity(assessment):
    from backend.tools.region_stage import level_band,youth_stage
    items=[]
    for row in assessment['segments']:
        value=row['value'];index=row['index_name']
        stages=[youth_stage(level_band(index,value+delta),row.get('scenario_signals',())) for delta in (-.01,0,.01)] if value is not None and index in ('S1','v3') else None
        items.append({'evidence_id':row['evidence_id'],'stages':stages,
                      'base_stage_stable':len(set(stages))==1 if stages else None})
    return {'tool':'sensitivity','tool_version':'regional-statistics-1','delta':.01,'items':items,
            'interpretation':'index-specific perturbation, not calibrated uncertainty'}


def policy_needs(assessment):
    """Describe selected-area needs; a segment count is not a resident count."""
    from backend.tools.regional_resources import need_profile
    groups={}
    for row in assessment['segments']:
        key=(row['sgg'],row['sex'],row['age_group'],row['index_name'],row['source_period'],digest(row['source_bands']))
        groups.setdefault(key,[]).append(row)
    cohorts=[];profiles=[]
    stable_by_id={r['evidence_id']:r['base_stage_stable'] for r in sensitivity(assessment)['items']}
    for key,rows in sorted(groups.items()):
        valid=[r for r in rows if r['stage'] is not None and r['value'] is not None and isfinite(r['value'])]
        stages=[r['stage'] for r in valid];n=len(valid);counts=Counter();pairs=Counter();cohort_id=digest(key)
        for row in rows:
            observed=row in valid;profile=need_profile(row);needs=profile['needs'] if observed else []
            counts.update(needs)
            for i,first in enumerate(needs):
                for second in needs[i+1:]:pairs[(first,second)]+=1
            profiles.append({'evidence_id':row['evidence_id'],'cohort_id':cohort_id,'dong_nm':row['dong_nm'],'comparable_segments':n,
                'priority_midrank':(sum(s<row['stage'] for s in stages)+.5*sum(s==row['stage'] for s in stages))/n if observed and n>=3 else None,
                'priority_review':row['stage']>=4 if observed else None,'base_stage_stable':stable_by_id[row['evidence_id']],
                **profile,'needs':needs,'need_basis':profile['need_basis'] if observed else 'insufficient_evidence',
                'measured_components':{},
                'estimated_people':None})
        cohorts.append({'cohort_id':cohort_id,'sgg':key[0],'sex':key[1],'age_group':key[2],'index_name':key[3],
            'source_period':key[4],'total_segments':len(rows),'observed_segments':n,'missing_segments':len(rows)-n,
            'priority_segments':sum(s>=4 for s in stages),'priority_share':sum(s>=4 for s in stages)/n if n else None,
            'need_counts':dict(sorted(counts.items())),
            'joint_needs':[{'needs':list(pair),'segments':count} for pair,count in sorted(pairs.items())]})
    return {'version':'policy-needs-2','cohorts':cohorts,'profiles':profiles,'population_estimate':None,
        'limitations':['선택한 동·집단의 기술 통계이며 주민 유병률·개인 판정·인과 원인이 아닙니다.',
            '상대 위치는 같은 척도·집단·기간의 등급 중간순위이며 위험 확률이 아닙니다. 3개 미만이면 산출하지 않습니다.',
            '관측 요인과 욕구는 다릅니다. 원천 요인 정의·욕구별 근거가 없으면 매핑하지 않으며 청년 지수는 관계 지원 조사 가설로만 사용합니다.',
            '임계값 민감도는 ±0.01 지수 변형 결과이며 보정된 불확실성이 아닙니다.']}
