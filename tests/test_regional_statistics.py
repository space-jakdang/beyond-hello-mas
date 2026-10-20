from copy import deepcopy
import pytest
from backend.tools.regional_statistics import summary,trend,run_tool
from backend.tools.regional_task import assess
from tests.test_regional_task import task
from tests.test_graph import service


def test_statistics_denominators_and_scale_boundaries(service):
    a=assess(service.settings,task());a=deepcopy(a);a['segments']=a['segments'][:3]
    a['segments'][0].update(value=None,stage=None)
    a['segments'][1].update(value=2,index_name='S1')
    a['segments'][2].update(value=100,index_name='other')
    s=summary(a)
    assert (s['total'],s['observed'],s['missing_rate'])==(3,2,1/3)
    assert sorted(d['mean'] for d in s['distributions'])==[2,100]
    assert s['blocked_evidence_ids']==[a['segments'][0]['evidence_id']]
    with pytest.raises(ValueError):run_tool('execute_code',service.settings,a)


def test_trend_uses_only_observed_past_months(service):
    a=assess(service.settings,task());t=trend(service.settings,a)
    assert t['series']
    assert all(p['ym']<='2025-09' for s in t['series'] for p in s['points'])
    assert all(s['points'][0]['change'] is None for s in t['series'])
    assert t['forecast'] is False


def test_source_and_base_rule_sensitivity(service):
    a=assess(service.settings,task());a['segments']=a['segments'][:1]
    a['segments'][0].update(index_name='S1',value=.291,stage=2)
    s=run_tool('sensitivity',service.settings,a)['items'][0]
    assert s['stages']==[2,2,1] and s['base_stage_stable'] is False
    a['segments'][0]['stage']=None
    assert run_tool('source_check',service.settings,a)['items'][0]['stage_missing'] is True


def test_trend_gaps_and_changed_age_bands_do_not_imply_change(service,monkeypatch):
    import backend.tools.regional_statistics as module
    from backend.tools.segments_v3 import load_segments
    a=assess(service.settings,task());a['segments']=a['segments'][:1]
    rows,source=load_segments(service.settings)
    selected=[r for r in rows if r.dong_cd==a['segments'][0]['dong_cd'] and r.sex=='M' and r.age_group=='youth' and r.ym in ('2025-07','2025-09')]
    monkeypatch.setattr(module,'load_segments',lambda settings:(selected,source))
    t=trend(service.settings,a)
    assert all(p['change'] is None for s in t['series'] for p in s['points'])
    assert t['input_hash']!=t['output_hash']
