"""Import the pinned public boundary subset; never reads analytical/private inputs."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

COMMIT='d5d5a821c8de6cc337d47eeca604d7af76271c9b'
SOURCE=f'https://raw.githubusercontent.com/vuski/admdongkor/{COMMIT}/ver20250701/HangJeongDong_ver20250701.geojson'


def export(raw, target):
    body=json.loads(raw)
    features=[]
    for feature in body['features']:
        p=feature['properties']
        if p['adm_cd'][:5] in ('11230','32010'):
            features.append({'type':'Feature','properties':{'dong_cd':p['adm_cd'],'dong_nm':p['adm_nm'].split()[-1],'sgg':p['adm_cd'][:5],'region_name':p['sggnm']},'geometry':feature['geometry']})
    assert len(features)==47 and len({f['properties']['dong_cd'] for f in features})==47
    result={'type':'FeatureCollection','features':sorted(features,key=lambda f:f['properties']['dong_cd'])}
    output=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()
    manifest={'version':'2025-07-01','crs':'EPSG:4326','source_url':SOURCE,'source_commit':COMMIT,'source_sha256':hashlib.sha256(raw).hexdigest(),'subset_sha256':hashlib.sha256(output).hexdigest(),'feature_count':47,'changes':'강남구/춘천시 선택, 속성 정리; 경계 좌표 변경 없음','attribution':'통계청 SGIS (공공누리 제1유형), 가공 vuski/admdongkor (CC BY 4.0)','license_url':'https://github.com/vuski/admdongkor/blob/'+COMMIT+'/LICENSE-DATA'}
    target.mkdir(parents=True,exist_ok=True)
    (target/'boundaries.geojson').write_bytes(output)
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    with urlopen(SOURCE,timeout=60) as response:raw=response.read()
    export(raw,Path(__file__).resolve().parents[1]/'data/geography')
