"""Local-only stage/arrears catalog, preserving provided and reviewed provenance."""
import csv
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from backend.app.config import ROOT, Settings
from backend.app.contracts import Resource
from backend.tools.catalog import load_catalog, validate_catalog
from scripts.import_seohee import inventory

VERSION='seohee-resources-3'
ALIASES={'N01':'kr-109','N03':'kr-129','S02':'seoul-120'}
REGIONS={'전국':'KR','서울':'11','강남':'11230','강원':'32','춘천':'32010'}
NEEDS={'위기상담':['emotional'],'접수·연계':['relationship','economic'],'고립은둔 전담':['relationship'],
    '심리상담':['emotional'],'일자리':['employment'],'생계위기':['economic'],'부채':['economic'],
    '주거':['housing'],'자립':['economic','relationship'],'관계·상담':['relationship','emotional'],
    '관계·공간':['relationship'],'소득·활동':['economic'],'자산형성':['economic'],'청년센터':['relationship'],
    '정신건강':['emotional'],'발굴·방문':['relationship'],'창업':['employment']}


def merge(rows,existing,source):
    ids=[r['id'] for r in rows]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate provided resource')
    result={r.id:r.model_copy(update={'schema_version':'3','catalog_version':VERSION,
        'provenance':[{'source':'curated-20261018-1','resource':r.model_dump(mode='json')}]}) for r in existing}
    for row in rows:
        if row['체납연계'] not in ('Y','N') or row['확인상태'] not in ('확인','주의'):raise ValueError('unknown provided resource status')
        resource_id=ALIASES.get(row['id'],'seohee-'+row['id'])
        previous=result.get(resource_id)
        provenance=[{'source':source,'row':row}]
        raw={'schema_version':'3','id':resource_id,'catalog_version':VERSION,
            'name':row['자원명'],'jurisdiction':[REGIONS[row['지역']]],
            'age_min':int(row['나이하한'] or 0),'age_max':int(row['나이상한'] or 120),
            'stage_min':int(row['최소단계']),'stage_max':int(row['최대단계']),
            'arrears_link':row['체납연계']=='Y','verification':'provided_confirmed' if row['확인상태']=='확인' else 'caution',
            'needs':NEEDS[row['유형']],'intensity':'high' if int(row['최소단계'])>=4 else 'medium' if int(row['최소단계'])==3 else 'low',
            'eligibility':'담당자가 신청 자격과 운영 상태를 확인해야 함','eligibility_tags':['confirmed:'+resource_id],
            'delivery':row['이용방식'],'access':'both','isolation_relevance':row['유형'],
            'source_url':None,'collected_at':'2026-10-18T00:00:00+09:00','evidence':row['비고'] or row['확인상태'],
            'provenance':provenance}
        if previous:
            # Reviewed access and eligibility remain authoritative; provided stage axes add to them.
            raw={**previous.model_dump(mode='json'),**{k:raw[k] for k in ('stage_min','stage_max','arrears_link','verification')},
                 'provenance':previous.provenance+provenance}
        result[resource_id]=Resource.model_validate(raw)
    return validate_catalog(list(result.values()))


def export(settings):
    if settings.data_mode!='local':raise ValueError('provided resources require local mode')
    root=settings.data_dir/'seohee';manifest=json.loads((root/'import.json').read_text())
    original=inventory(root);hashes=dict(original);hashes.pop('import.json',None)
    if hashes!=manifest['files']:raise ValueError('source checksum mismatch')
    files=list(root.rglob('welfare_resources.csv'))
    if len(files)!=1:raise ValueError('one resource file required')
    with files[0].open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
    if len(rows)!=32:raise ValueError('expected provided 32 resources')
    existing=load_catalog(ROOT/'data/catalog/curated-20261018-1/resources.csv')
    resources=merge(rows,existing,str(files[0].relative_to(root)))
    target=settings.data_dir/'resources-v3.csv'
    with NamedTemporaryFile(mode='w',encoding='utf-8',newline='',dir=target.parent,delete=False) as stream:
        temporary=Path(stream.name)
        try:
            writer=csv.DictWriter(stream,fieldnames=list(Resource.model_fields));writer.writeheader()
            for r in resources:
                row=r.model_dump(mode='json')
                for key in ('jurisdiction','needs','eligibility_tags','provenance'):row[key]=json.dumps(row[key],ensure_ascii=False)
                writer.writerow(row)
            stream.flush()
            if inventory(root)!=original:raise ValueError('source changed')
            load_catalog(temporary)
            os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)
    return {'provided':len(rows),'reviewed':len(existing),'merged':len(resources),'version':VERSION}


if __name__=='__main__':print(export(Settings(data_mode='local')))
