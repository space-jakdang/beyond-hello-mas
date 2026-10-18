from copy import deepcopy
import pytest
from backend.app.config import Settings
from backend.tools.weekly_signals import alarm, audit, load, synthetic
from backend.tools.neighborhoods import group_analysis


def test_strict_thresholds_consecutive_weeks_and_special_group():
    assert alarm([.95,.94])=='none'
    assert alarm([.949,.94])=='weak'
    assert alarm([.89,.89])=='strong'
    assert alarm([.94]*4)=='strong'
    assert alarm([.89,None,.89])=='none'
    assert alarm([.94,.94],.90)=='none'
    assert alarm([.94]*4,.90)=='strong'
    # A displayed .9500 can come from an unrounded quotient strictly below .95.
    assert alarm([1.8999/2,.94])=='weak'


def test_fixture_audit_rejects_lookahead_and_false_alarms():
    rows=synthetic()
    original=[(m['source_alarm'],m['ratio']) for r in rows for m in r['metrics'].values()]
    assert audit(rows)['matched_alerts']==368
    assert original==[(m['source_alarm'],m['ratio']) for r in rows for m in r['metrics'].values()]
    group=rows[:23]
    assert all(r['metrics']['T1b']['baseline'] is None for r in group[:8])
    assert group[8]['metrics']['T1b']['baseline']==1
    changed=deepcopy(rows);changed[8]['metrics']['T1b']['baseline']=.8
    with pytest.raises(ValueError,match='baseline'):audit(changed)
    changed=deepcopy(rows);changed[0]['metrics']['T1b']['signal']='strong'
    with pytest.raises(ValueError,match='warmup'):audit(changed)
    changed=deepcopy(rows);changed[9]['metrics']['R1']['signal']='none'
    with pytest.raises(ValueError,match='alarm'):audit(changed)


def test_week_selection_is_district_signal_and_never_applied_to_other_months():
    settings=Settings(_env_file=None,llm_mode='fake')
    weekly=load(settings);assert len(weekly['weeks'])==23
    first=group_analysis(settings,week='2025-07-07',card_age='30s')
    strong=group_analysis(settings,week='2025-09-08',card_age='30s')
    assert first['metadata']['selected_week']=='2025-07-07'
    youth=[r for r in strong['segments'] if r['age_group']=='youth' and r['ym']=='2025-09']
    assert youth and all(r['stage']==5 for r in youth)
    assert all('weekly' not in r for r in strong['segments'] if r['ym']!='2025-09')
    assert all('weekly' not in r for r in strong['segments'] if r['age_group']!='youth')


def test_special_group_strong_signal_still_reports_four_declining_weeks():
    group=[r for r in synthetic() if (r['sgg'],r['sex'],r['age_band'])==('32010','F','20s')][:12]
    for i in range(8,12):
        for metric in group[i]['metrics'].values():
            metric.update(value=.94,baseline=1,ratio=.94,signal='strong' if i==11 else 'none')
    audit(group)
    assert group[-1]['metrics']['R1']['consecutive_weeks']==4


def test_priority_is_explicit_and_capped():
    settings=Settings(_env_file=None,llm_mode='fake')
    normal=group_analysis(settings,week='2025-07-07',card_age='30s')
    priority=group_analysis(settings,week='2025-07-07',card_age='20s')
    for before,after in zip(normal['segments'],priority['segments']):
        applied=after['age_group']=='youth' and after['sex']=='M' and after['ym']=='2025-07'
        assert after['priority_group_applied']==applied
        assert after['stage']==min(5,before['stage']+1) if applied else after['stage']==before['stage']


def test_ratio_and_baseline_corruption_is_rejected():
    for key in ('ratio','baseline'):
        rows=synthetic();rows[8]['metrics']['R1'][key]+=.001
        with pytest.raises(ValueError,match='ratio|baseline'):audit(rows)
