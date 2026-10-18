import copy
import json
from datetime import date
from pathlib import Path
import pytest
from backend.tools.curation import curate, export
from backend.tools.catalog import load_catalog
from backend.tools.matching import MatchRequest, match


def entries():
    return json.loads(Path('data/catalog/reviewed.json').read_text())


def test_real_catalog_and_confirmation_gate(tmp_path):
    data=entries()
    resources, report=curate(data)
    assert len(resources)==30 and not report['rejected']
    assert all(report['jurisdictions'].values())
    assert export(data,tmp_path)==export(data,tmp_path)
    assert load_catalog(tmp_path/'resources.csv')==resources
    request=MatchRequest(sgg='11230',age_min=30,age_max=39,needs=['relationship'],intensity='low',as_of=date(2026,10,18))
    assert match(resources,request)['shortfall']==3
    confirmed=request.model_copy(update={'eligibility':{'confirmed:seoul-120':True,'confirmed:seoul-365':True,'confirmed:seoul-itta':True}})
    assert len(match(resources,confirmed)['recommendations'])==3
    assert match(resources,confirmed.model_copy(update={'sgg':'32010'}))['shortfall']==3
    changed=copy.deepcopy(data);changed[0]['resource']['name']='new name'
    with pytest.raises(ValueError,match='already exists'):
        export(changed,tmp_path)


def test_partial_failures_do_not_adopt_unreviewed_or_duplicate_entries():
    data=entries()[:4]
    data[1]['status']='needs_review'
    data[2]['field_notes'].pop('age')
    data.append(copy.deepcopy(data[0]))
    resources,report=curate(data)
    assert len(resources)==1 and len(report['rejected'])==4
    assert report['target_shortfall']==29
    data=entries()[:1];data[0]['resource']['eligibility_tags']=[]
    assert not curate(data)[0]
