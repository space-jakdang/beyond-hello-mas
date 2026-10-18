"""Independent table: 2026-10-18 bundle, 5단계_위험도.md §3-2(다) 최종 판정표.
Non-youth rows check provided-stage preservation, not independent clinical truth.
"""
TABLE={'none':[3,3,3,2,1],'weak':[4,4,3,3,3],'strong':[5,4,4,4,4],'both':[5,5,5,5,5]}


def regional(row,signals=(),priority=False):
    if row.value is None:return None
    if row.index_name not in ('S1','v3'):return row.source_stage
    if row.index_name=='S1':band=sum(row.value>edge for edge in (.206,.227,.241,.291))
    else:band=sum(row.value<edge for edge in (.54,.45,.16,-.08))
    active=[signal for signal in signals if signal!='none']
    category='both' if len(active)>1 else active[0] if active else 'none'
    return min(5,TABLE[category][band]+int(priority))
