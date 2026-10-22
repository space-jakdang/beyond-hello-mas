import pytest
from backend.tools.region_stage import level_band, youth_stage, rank_stage, classify
from backend.tools.segments_v3 import load_segments
from backend.app.config import Settings
from scripts.generate_groups import generate


def test_youth_thresholds_and_signal_table():
    assert [level_band('S1',v) for v in [.206,.227,.241,.291,.292]]==list(range(5))
    assert [level_band('v3',v) for v in [.54,.45,.16,-.08,-.09]]==list(range(5))
    assert [youth_stage(b) for b in range(5)]==[3,3,3,2,1]
    assert youth_stage(4,['weak'])==3
    assert youth_stage(1,['weak'])==4
    assert youth_stage(0,['strong'])==5
    assert youth_stage(4,['strong'])==4
    assert youth_stage(4,['weak','weak'])==5
    assert youth_stage(3,[],True)==3
    assert youth_stage(0,['strong'],True)==5
    assert youth_stage(None,['strong']) is None
    assert [rank_stage(i) for i in [1,2,3,4,5,9,10,13,14,22]]==[5,5,4,4,3,3,2,2,1,1]
    with pytest.raises(ValueError):rank_stage(0)


def test_classify_keeps_comparisons_and_missing_separate():
    row=generate()[1]
    preferred=row.model_copy(update={'index_name':'G_gangnam_rank','source_stage':4,'preferred':True})
    other=row.model_copy(update={'source_stage':5,'preferred':False})
    result=classify([preferred,other])
    assert result['dongs'][0]['stage']==4
    assert classify([preferred.model_copy(update={'value':None})])['dongs'][0]['stage'] is None
    assert not result['metadata']['individual_diagnosis']


def test_v3_sample_and_api_are_repeatable(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    settings=Settings(_env_file=None,llm_mode='fake')
    import backend.tools.neighborhoods as neighborhoods
    monkeypatch.setattr(neighborhoods,'load_segments',lambda *_:pytest.fail('v3 must not load legacy segments'))
    rows,_=load_segments(settings)
    assert classify(rows)==classify(rows)
    with TestClient(create_app(settings)) as client:
        response=client.get('/analysis/groups')
    assert response.status_code==200
    data=response.json()
    assert len(data['segments'])==2256 and data['coverage']['matched']==47
    assert data['metadata']['rule_version']=='seohee-region-2'
    assert not data['period_aggregate']
