"""Read-only analysis; synthetic cells never inherit a real neighborhood's geometry."""
import hashlib
import json
from math import isfinite
from backend.app import config
from backend.tools.segments import load_segments
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
    return {'data_mode':settings.data_mode,'months':sorted({r.ym for r in rows}),
            'neighborhoods':list(dongs.values()),'segments':result['segments'],'dongs':result['dongs'],
            'metadata':{**result['metadata'],'generator_version':source.get('generator_version'),'indicators':[i.model_dump(mode='json') for i in default_rules().indicators]},
            'geometry':geo,'geography':provenance,'coverage':{'matched':len(geo['features']),'total':len(dongs),'unmatched_codes':unmatched}}
