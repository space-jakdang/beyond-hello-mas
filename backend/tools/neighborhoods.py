"""Read-only analysis; synthetic cells never inherit a real neighborhood's geometry."""
import hashlib
import json
from math import isfinite
from backend.app import config
from backend.tools.segments import MONTHS, load_segments
from backend.tools.staging import classify
from backend.tools.indicators import default_rules


def validate_boundaries(body):
    if body.get('type')!='FeatureCollection':raise ValueError('invalid boundary collection')
    seen=set()
    for f in body['features']:
        p=f['properties'];code=p['dong_cd'];g=f['geometry']
        if code in seen or len(code)!=8 or not code.isdigit() or p['sgg']!=code[:5]:raise ValueError('invalid boundary code')
        seen.add(code)
        if g['type'] not in ('Polygon','MultiPolygon'):raise ValueError('polygon required')
        polygons=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
        if not polygons:raise ValueError('empty boundary')
        for polygon in polygons:
            if not polygon:raise ValueError('empty polygon')
            for ring in polygon:
                if len(ring)<4 or ring[0]!=ring[-1]:raise ValueError('unclosed ring')
                for point in ring:
                    if len(point)!=2 or any(type(v) not in (int,float) or not isfinite(v) for v in point) or not -180<=point[0]<=180 or not -90<=point[1]<=90:
                        raise ValueError('invalid WGS84 point')
    return body


def boundaries():
    folder=config.ROOT/'data/geography'
    raw=(folder/'boundaries.geojson').read_bytes()
    metadata=json.loads((folder/'manifest.json').read_text())
    if metadata['crs']!='EPSG:4326' or hashlib.sha256(raw).hexdigest()!=metadata['subset_sha256']:
        raise ValueError('boundary provenance mismatch')
    body=validate_boundaries(json.loads(raw))
    if len(body['features'])!=metadata['feature_count']:raise ValueError('boundary count mismatch')
    return body,metadata


def geometry(settings,dongs):
    if settings.data_mode=='sample':
        # shortcut: non-geographic cells preserve synthetic identities; use real boundaries only with local input.
        features=[]
        for index,(code,info) in enumerate(sorted(dongs.items())):
            x=index%8;y=index//8
            features.append({'type':'Feature','properties':info,'geometry':{'type':'Polygon','coordinates':[[[x,y],[x+.85,y],[x+.85,y+.85],[x,y+.85],[x,y]]]}})
        geo={'type':'FeatureCollection','features':features}
        provenance={'version':'synthetic-grid-1','crs':'synthetic-cartesian','attribution':'합성 격자 · 실제 지리 위치 아님'}
        unmatched=[]
    else:
        geo,provenance=boundaries()
        matched={f['properties']['dong_cd']:f for f in geo['features'] if f['properties']['dong_cd'] in dongs and f['properties']['dong_nm']==dongs[f['properties']['dong_cd']]['dong_nm']}
        unmatched=sorted(set(dongs)-set(matched))
        geo={**geo,'features':list(matched.values())}
    return geo,provenance,unmatched


def analysis(settings):
    rows,source=load_segments(settings)
    result=classify(rows)
    dongs={}
    lookup={}
    for row in rows:
        info={'dong_cd':row.dong_cd,'dong_nm':row.dong_nm,'sgg':row.sgg}
        if row.dong_cd in dongs and dongs[row.dong_cd]!=info:raise ValueError('neighborhood identity changed')
        dongs[row.dong_cd]=info
        lookup[(row.ym,row.dong_cd,row.age_band)]=row
    for segment in result['segments']:
        row=lookup[(segment['ym'],segment['dong_cd'],segment['age_band'])]
        segment['indicators']=row.indicators
    geo,provenance,unmatched=geometry(settings,dongs)
    return {'data_mode':settings.data_mode,'months':sorted(set(MONTHS)|{r.ym for r in rows}),
            'neighborhoods':list(dongs.values()),'segments':result['segments'],'dongs':result['dongs'],
            'metadata':{**result['metadata'],'generator_version':source.get('generator_version'),'indicators':[i.model_dump(mode='json') for i in default_rules().indicators]},
            'geometry':geo,'geography':provenance,'coverage':{'matched':len(geo['features']),'total':len(dongs),'unmatched_codes':unmatched}}


def group_analysis(settings,week=None,card_age="20s"):
    from backend.tools.segments_v3 import load_segments as load_groups
    from backend.tools.region_stage import classify as classify_groups
    rows,source=load_groups(settings)
    result=classify_groups(rows)
    from backend.tools.weekly_signals import load as load_weekly
    from backend.tools.region_stage import youth_stage
    weekly=load_weekly(settings)
    selected_week=week or weekly['weeks'][-1]
    if selected_week not in [*weekly['weeks'],'all'] or card_age not in ('20s','30s','all'):raise ValueError('unknown weekly selection')
    combined=selected_week=='all' or card_age=='all'
    selected={(r['sgg'],r['sex']):r for r in weekly['rows'] if r['week']==selected_week and r['age_band']==card_age}
    for segment in result['segments']:
        segment['priority_group_applied']=False
        segment['exploratory_replay']=False
        if combined or segment['index_name'] not in ('S1','v3') or segment['ym'] not in (None,selected_week[:7]):continue
        signal=selected.get((segment['sgg'],segment['sex']))
        segment['weekly']=signal
        if signal:
            segment['exploratory_replay']=segment['ym'] is None
            segment['priority_group_applied']=card_age=='20s' and segment['sex']=='M'
            segment['stage']=youth_stage(segment['level_band'],[m['signal'] for m in signal['metrics'].values()],segment['priority_group_applied'])
    for dong in result['dongs']:
        dong['stage']=max((s['stage'] for s in result['segments'] if s['ym']==dong['ym'] and s['dong_cd']==dong['dong_cd'] and s['preferred'] and s['stage'] is not None),default=None)
    result['metadata'].update(card_signals_applied=not combined,selected_week=selected_week,card_age=card_age,
                              weekly_scope='district × sex × age; not dong observations')
    result['weekly']=weekly
    dongs={}
    for row in rows:
        info={'dong_cd':row.dong_cd,'dong_nm':row.dong_nm,'sgg':row.sgg}
        if row.dong_cd in dongs and dongs[row.dong_cd]!=info:raise ValueError('neighborhood identity changed')
        dongs[row.dong_cd]=info
    geo,provenance,unmatched=geometry(settings,dongs)
    return {**result,'data_mode':settings.data_mode,'months':sorted({r.ym for r in rows if r.ym}),
            'neighborhoods':list(dongs.values()),'geometry':geo,'geography':provenance,
            'coverage':{'matched':len(geo['features']),'total':len(dongs),'unmatched_codes':unmatched},
            'period_aggregate':any(r.ym is None for r in rows),'metadata':{**result['metadata'],'source':source}}
