"""Source-specific regional outreach order, never an individual diagnosis."""
from collections import defaultdict
from backend.tools.indicators import digest
from backend.tools.segments_v3 import validate

VERSION='seohee-region-2'


def level_band(index,value):
    if value is None:return None
    if index=='S1':
        return next((i for i,limit in enumerate((.206,.227,.241,.291)) if value<=limit),4)
    if index=='v3':
        return next((i for i,limit in enumerate((.54,.45,.16,-.08)) if value>=limit),4)
    raise ValueError('youth level requires S1 or v3')


def youth_stage(band,signals=(),priority=False):
    if band is None:return None
    if band not in range(5) or any(s not in ('none','weak','strong') for s in signals):raise ValueError('invalid regional signal')
    active=sum(s!='none' for s in signals)
    if active>=2 or (band==0 and 'strong' in signals):stage=5
    elif 'strong' in signals or (band<=1 and 'weak' in signals):stage=4
    elif band<=2 or 'weak' in signals:stage=3
    elif band==3:stage=2
    else:stage=1
    return min(5,stage+bool(priority))


def rank_stage(rank):
    if type(rank) is not int or not 1<=rank<=22:raise ValueError('invalid Gangnam rank')
    return next(stage for cutoff,stage in ((2,5),(4,4),(9,3),(13,2),(22,1)) if rank<=cutoff)


def classify(rows):
    validate(rows)
    result=[]
    for row in rows:
        band=level_band(row.index_name,row.value) if row.index_name in ('S1','v3') else None
        stage=youth_stage(band) if row.index_name in ('S1','v3') else row.source_stage
        if row.value is None:stage=None
        result.append({**row.model_dump(mode='json'),'stage':stage,'base_stage':stage,'level_band':band,
                       'stage_scale':f'{row.index_name}:base','reachable_base_stages':[1,2,3] if row.index_name in ('S1','v3') else [1,2,3,4,5],
                       'priority_review':None,'priority_criterion_status':'not_established',
                       'interpretation':'먼저 찾아갈 순서','comparable_across_regions':False})
    groups=defaultdict(list)
    for r in result:groups[(r['ym'],r['dong_cd'])].append(r)
    return {'segments':result,'metadata':{'rule_version':VERSION,'input_hash':digest([r.model_dump(mode='json') for r in rows]),
        'provisional':True,'interpretation':'먼저 찾아갈 순서','individual_diagnosis':False,
        'card_signals_applied':False,'age_crosswalk':'source-specific','stage_contract_version':'regional-stage-scope-1',
        'common_priority_criterion':'not_established','comparable_across_groups':False},
        'dongs':[{'ym':ym,'dong_cd':dong,'stage':max((r['stage'] for r in items if r['preferred'] and r['stage'] is not None),default=None)} for (ym,dong),items in groups.items()]}
