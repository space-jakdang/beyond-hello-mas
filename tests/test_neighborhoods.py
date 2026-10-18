from copy import deepcopy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.config import Settings
from backend.app.analysis_routes import analysis_router
from backend.tools.neighborhoods import analysis,boundaries,validate_boundaries
from backend.tools.segments import load_segments
from backend.tools.staging import classify


def test_sample_geometry_and_analysis_preserve_existing_results():
    settings=Settings(data_mode='sample',llm_mode='fake')
    result=analysis(settings)
    baseline=classify(load_segments(settings)[0])
    assert result['coverage']=={'matched':47,'total':47,'unmatched_codes':[]}
    assert len(result['segments'])==1692 and len(result['months'])==6
    assert result['geography']['crs']=='synthetic-cartesian'
    assert [(r['stage'],r['score']) for r in result['segments']]==[(r['stage'],r['score']) for r in baseline['segments']]
    assert result['geometry']['features'][0]['properties']['dong_nm'].startswith('합성동')


def test_public_boundary_contract_and_malformed_geometry():
    body,metadata=boundaries()
    assert len(body['features'])==47 and metadata['crs']=='EPSG:4326'
    for alter in ('duplicate','coordinate','ring'):
        bad=deepcopy(body)
        if alter=='duplicate':bad['features'].append(bad['features'][0])
        else:
            g=bad['features'][0]['geometry'];polygon=g['coordinates'] if g['type']=='Polygon' else g['coordinates'][0]
            if alter=='coordinate':polygon[0][0]=[float('nan'),0]
            else:polygon[0].pop()
        with pytest.raises(ValueError):validate_boundaries(bad)


def test_missing_local_never_falls_back_to_sample(tmp_path,monkeypatch):
    from backend.app import config
    monkeypatch.setattr(config,'ROOT',tmp_path)
    app=FastAPI();app.include_router(analysis_router(Settings(data_mode='local',llm_mode='fake')))
    with TestClient(app) as client:
        response=client.get('/analysis?data_mode=sample')
        assert response.status_code==503 and str(tmp_path) not in response.text


def test_local_join_requires_both_code_and_name(monkeypatch):
    from backend.tools import neighborhoods
    rows,source=load_segments(Settings(data_mode='sample',llm_mode='fake'))
    old=rows[0].dong_cd
    rows=[r.model_copy(update={'dong_cd':'11230510','dong_nm':'신사동'}) if r.dong_cd==old else r for r in rows]
    monkeypatch.setattr(neighborhoods,'load_segments',lambda settings:(rows,source))
    result=analysis(Settings(data_mode='local',llm_mode='fake'))
    assert result['coverage']['matched']==1 and len(result['coverage']['unmatched_codes'])==46
    rows[:]=[r.model_copy(update={'dong_nm':'다른동'}) if r.dong_cd=='11230510' else r for r in rows]
    assert analysis(Settings(data_mode='local',llm_mode='fake'))['coverage']['matched']==0


def test_missing_whole_month_remains_on_analysis_timeline(monkeypatch):
    from backend.tools import neighborhoods
    rows,source=load_segments(Settings(data_mode='sample',llm_mode='fake'))
    monkeypatch.setattr(neighborhoods,'load_segments',lambda settings:([r for r in rows if r.ym!='2025-09'],source))
    result=analysis(Settings(data_mode='sample',llm_mode='fake'))
    assert '2025-09' in result['months'] and '2025-09' in result['metadata']['missing_months']
    assert not any(r['ym']=='2025-09' for r in result['segments'])
