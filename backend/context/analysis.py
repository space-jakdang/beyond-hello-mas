"""Source-preserving context tools; household ratios never use person denominators."""
from backend.context.contracts import fact_dict,METRICS
from backend.tools.indicators import digest

FACT_COLUMNS=('fact_id','metric','value','unit','reference_year','geography_level','geography_code','geography_version',
              'population','age_definition','sex','source','source_table','source_items','source_dimensions','published_at','status','reason')


def checked_fact(fact):
    parsed=fact_dict({k:v for k,v in fact.items() if k!='fact_id'})
    if parsed['fact_id']!=fact['fact_id']:raise ValueError('regional fact checksum mismatch')
    return parsed


def rates(profile):
    facts={f['metric']:f for f in profile.get('facts',[])}
    result=[]
    for numerator,denominator in (('one_person_households','general_households' if 'general_households' in facts else 'total_households'),('senior_population','total_population'),('youth_population','total_population')):
        first=facts.get(numerator);second=facts.get(denominator)
        if not first or not second:continue
        first,second=checked_fact(first),checked_fact(second)
        keys=('unit','geography_level','geography_code','geography_version','reference_year','population','sex','source')
        if any(first[k]!=second[k] for k in keys):continue
        if first['status']!='observed' or second['status']!='observed' or second['value']<=0 or first['value']>second['value']:continue
        if second['age_definition']!='all_ages' or first['sex']!='all':continue
        if numerator=='one_person_households' and first['age_definition']!='all_ages':continue
        result.append({'metric':numerator+'_share','value':100*first['value']/second['value'],'unit':'percent',
            'reference_year':first['reference_year'],'geography_level':first['geography_level'],
            'fact_ids':[first['fact_id'],second['fact_id']],'meaning':'aggregate composition, not isolation prevalence or service demand'})
    return result


def briefing(profiles,dong_codes=None):
    selected=[p for code,p in sorted(profiles.items()) if dong_codes is None or code in dong_codes]
    selected=[{**p,'facts':[checked_fact(fact) for fact in p['facts']]} for p in selected]
    return {'version':'regional-context-review-1','areas':[{'dong_cd':p['request']['dong_cd'],
        'dong_nm':p.get('identity',{}).get('dong_nm'),'status':p['status'],'input_hash':p['input_hash'],
        'facts':[{k:f[k] for k in FACT_COLUMNS} for f in p['facts']],
        'rates':rates(p),'questions':['확인 필요: '+METRICS[f['metric']][0] for f in p['facts'] if f['status']!='observed'],
        'limitations':p.get('limitations',[])} for p in selected],
        'claim_limits':['지역 구성은 서비스 필요·참여 장벽·인과 원인의 관측이 아닙니다.','조회 시점 자료의 과거 가용성과 경계 동일성은 별도 확인이 필요합니다.']}


def context_tool(name,assessment):
    profiles=assessment.get('regional_context',{})
    result=briefing(profiles)
    if name=='regional_comparison':
        from backend.context.contracts import comparable
        areas={area['dong_cd']:area for area in result['areas']}
        comparisons=[]
        for code,profile in sorted(areas.items()):
            for fact in profile['facts']:
                if fact['geography_level']!='dong':continue
                peers=[f for other,p in areas.items() if other!=code for f in p['facts'] if f['geography_code']!=fact['geography_code'] and comparable(fact,f)]
                if not peers:continue
                comparisons.append({'dong_cd':code,'fact_id':fact['fact_id'],'peer_fact_ids':[f['fact_id'] for f in peers],
                    'peer_count':len(peers),'peer_mean':sum(f['value'] for f in peers)/len(peers),
                    'difference':fact['value']-sum(f['value'] for f in peers)/len(peers)})
        result={'version':result['version'],'comparisons':comparisons,'comparison_use':'absolute aggregate size only; composition-rate comparisons not supplied; no disparity or risk ranking','scope':'distinct measured dongs with matching definitions; district context excluded; not a risk ranking'}
    return {'tool':name,**result,'input_hash':digest({code:p['input_hash'] for code,p in profiles.items()})}


def observed_ids(view):
    result=set()
    for area in view.get('areas',[]):
        for item in area['facts']:
            fact=dict(zip(view['fact_columns'],item)) if isinstance(item,list) else item
            if fact['status']=='observed':result.add(fact['fact_id'])
    return result


def validate_notes(notes,assessment,shown=None,extra_fact_ids=()):
    areas=shown['areas'] if shown is not None else briefing(assessment.get('regional_context',{}))['areas']
    known=observed_ids(shown if shown is not None else {'areas':areas})
    all_known={f['fact_id'] for p in assessment.get('regional_context',{}).values() for f in p['facts'] if f['status']=='observed'}
    known|=all_known&set(extra_fact_ids)
    for note in notes:
        if not note['fact_ids'] or not set(note['fact_ids'])<=known:raise ValueError('unobserved regional context reference')
    return notes


def model_briefing(value):
    result={**value,'areas':[]}
    columns=list(FACT_COLUMNS)
    result['fact_columns']=columns
    for area in value['areas']:
        result['areas'].append({**area,'facts':[[fact[k] for k in columns] for fact in area['facts']]})
    return result


def short_fact_references(payload,profiles):
    import json
    aliases={'R'+str(i+1):identifier for i,identifier in enumerate(sorted({f['fact_id'] for p in profiles for f in p.get('facts',[])}))}
    encoded=json.dumps(payload,ensure_ascii=False)
    for short,canonical in aliases.items():encoded=encoded.replace(json.dumps(canonical),json.dumps(short))
    view=json.loads(encoded)
    view['regional_reference_note']='Use short R identifiers exactly for regional fact references; the server restores canonical IDs.'
    return view,aliases
