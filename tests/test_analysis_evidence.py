from backend.tools.weekly_signals import synthetic
from eval.analysis_evidence import weekly_sensitivity, weight_sensitivity
from scripts.generate_groups import generate


def test_weekly_comparison_keeps_denominators_and_prior_only():
    rows = synthetic()
    baseline = weekly_sensitivity(rows)
    assert all(r['compared_alerts'] + r['unavailable_alerts'] == 368 for r in baseline)
    assert baseline[1]['changed_alerts'] == 0
    assert baseline[1]['compared_alerts'] == 240
    assert baseline[2]['compared_alerts'] == 208
    # An isolated last observation can change the last alarm only, not its baseline or history.
    rows[-1]['metrics']['T1b']['value'] = .01
    altered = weekly_sensitivity(rows)
    assert all(abs(a['changed_alerts'] - b['changed_alerts']) <= 1 for a,b in zip(baseline, altered))


def test_weight_reference_and_missing_components():
    rows = [r for r in generate() if r.index_name == 'G_chuncheon'][:3]
    assert rows
    rows = [r.model_copy(update={'components': {'structure': i, 'visibility_risk': 2-i}}) for i,r in enumerate(rows)]
    # Put synthetic rows in the same cohort while retaining unique dong identities.
    rows = [r.model_copy(update={'ym': '2025-07','sex': 'M','age_group': 'midlife','dong_cd': str(i), 'preferred': True}) for i,r in enumerate(rows)]
    result = weight_sensitivity(rows)
    assert result[1]['reversed_pairs'] == result[1]['max_rank_shift'] == 0
    assert result[1]['compared_pairs'] == 3
    assert weight_sensitivity([rows[0].model_copy(update={'components': {}})])[0]['status'] == 'missing_components'
