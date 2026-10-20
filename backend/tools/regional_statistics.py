"""Descriptive evidence only: no invented time points or cross-region scores."""
from collections import Counter
from math import isfinite
from statistics import mean, median
from backend.tools.indicators import digest
from backend.tools.segments_v3 import load_segments


def summary(assessment):
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
            'input_hash':assessment['metadata']['input_hash'],'causal_claim':False,
            'confidence_interval':None,'cross_region_comparable':False}


def trend(settings,assessment):
    rows,_=load_segments(settings)
    task=assessment['task']
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
            'data_mode':assessment['data_mode'],'input_hash':inputs_hash,'output_hash':digest(result),'forecast':False}


def source_check(assessment):
    return {'tool':'source_check','tool_version':'regional-statistics-1','items':[
        {'evidence_id':r['evidence_id'],'source_file':r['source_file'],'source_period':r['source_period'],
         'source_bands':r['source_bands'],'flags':r.get('flags',[]),'value_missing':r['value'] is None,
         'stage_missing':r['stage'] is None,'status':'missing' if r['value'] is None or r['stage'] is None else 'observed'} for r in assessment['segments']]}


def run_tool(name,settings,assessment):
    if name=='summary':return summary(assessment)
    if name=='trend':return trend(settings,assessment)
    if name=='source_check':return source_check(assessment)
    if name=='sensitivity':return sensitivity(assessment)
    raise ValueError('unsupported statistics tool')


def sensitivity(assessment):
    from backend.tools.region_stage import level_band,youth_stage
    items=[]
    for row in assessment['segments']:
        value=row['value'];index=row['index_name']
        stages=[youth_stage(level_band(index,value+delta)) for delta in (-.01,0,.01)] if value is not None and index in ('S1','v3') else None
        items.append({'evidence_id':row['evidence_id'],'stages':stages,
                      'base_stage_stable':len(set(stages))==1 if stages else None})
    return {'tool':'sensitivity','tool_version':'regional-statistics-1','delta':.01,'items':items,
            'interpretation':'index-specific perturbation, not calibrated uncertainty'}
