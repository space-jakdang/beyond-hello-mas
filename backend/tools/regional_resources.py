"""Provisional evidence-to-need mapping plus existing strict catalog filters."""
import re
from math import isfinite
from backend.tools.matching import MatchRequest, map_intensity, match

NEEDS=('relationship','economic','housing','employment','health','emotional')


def source_ages(bands):
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
    return (min(p[0] for p in parsed),max(p[1] for p in parsed)) if parsed else None


def needs_for(row):
    needs=set()
    if row['value'] is not None and row['index_name'] in ('S1','v3'):needs.add('relationship')
    for key,value in (row.get('components') or {}).items():
        if type(value) in (float,int) and isfinite(value) and value>0:
            if key in NEEDS:needs.add(key)
            if key=='activity_deficit':needs.add('relationship')
    return sorted(needs)


def candidates(assessment,statistics,resources):
    rows=[]
    blocked=set(statistics.get('blocked_evidence_ids',[]))
    profiles={p['evidence_id']:p for p in statistics.get('summary',{}).get('policy_needs',{}).get('profiles',[])}
    for row in assessment['segments']:
        base={k:row[k] for k in ('evidence_id','dong_cd','dong_nm','sgg','sex','age_group','stage','source_bands')}
        needs=needs_for(row);ages=source_ages(row['source_bands'])
        reason=('statistics_unreviewed' if statistics.get('status')!='reviewed' else
                'insufficient_observation' if row['stage'] is None or row['evidence_id'] in blocked else
                'unknown_source_age' if ages is None else 'unmapped_evidence' if not needs else None)
        filtered=reason is None
        result={'recommendations':[],'excluded':[],'shortfall':3,'uncovered_needs':needs}
        if reason is None:
            request=MatchRequest(sgg=row['sgg'],age_min=ages[0],age_max=ages[1],needs=needs,stage=row['stage'],
                intensity=map_intensity(row['stage']),as_of=assessment['task']['as_of'])
            result=match(resources,request)
            if not result['recommendations']:reason='no_eligible_catalog_candidates'
        evidence={'version':'resource-decision-1', 'observation':{k:row.get(k) for k in
                    ('evidence_id','index_name','value','source_period','components','source_bands')},
                  'mapping_version':'regional-needs-1','provisional_needs':needs,'statistical_context':profiles.get(row['evidence_id']),
                  'filter_request':request.model_dump(mode='json') if filtered else None,
                  'catalog_metadata':result.get('metadata'),
                  'presented_candidates':[{'id':c['id'],'name':c['name'],'needs':c['needs'],
                      'source_url':c.get('source_url'),'collected_at':c.get('collected_at'),
                      'eligibility':c['eligibility'],'valid_until':c.get('valid_until')} for c in result['recommendations']],
                  'unknown_conditions':['individual_eligibility','application_acceptance','remaining_capacity'],
                  'model_reason':None}
        rows.append({**base,**result,'decision_evidence':evidence,'needs':needs,'age_range':ages,'reason':reason,
                     'statistical_context':profiles.get(row['evidence_id']),'catalog_filter_performed':filtered,'status':'candidate' if result['recommendations'] else 'needs_human',
                     'mapping_version':'regional-needs-1','provisional':True,'remaining_capacity':None,
                     'allocation_performed':False,'as_of':assessment['task']['as_of']})
    return rows
