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


def test_local_lineage_normalizes_names_and_rejects_tampering(tmp_path, monkeypatch):
    import hashlib
    import json
    import unicodedata
    from types import SimpleNamespace
    import pytest
    import eval.analysis_evidence as module
    root = tmp_path / 'seohee'; root.mkdir()
    name = unicodedata.normalize('NFD', '원천.csv')
    (root / name).write_text('source')
    checksum = hashlib.sha256(b'source').hexdigest()
    (root / 'import.json').write_text(json.dumps({'files': {name: checksum}}))
    row = generate()[0].model_copy(update={'source_file': '원천.csv'})
    monkeypatch.setattr(module, 'load_segments', lambda _: ([row], {'input_hash': 'fixture'}))
    monkeypatch.setattr(module, 'load_weekly', lambda _: {'rows': synthetic(), 'metadata': {'synthetic': True}})
    settings = SimpleNamespace(data_mode='local', data_dir=tmp_path)
    report = module.evaluate(settings)
    assert report['lineage'][0]['source_sha256'] == checksum
    assert report['missingness']['unclassified_when_missing'] == 1
    assert report['actual_isolation_accuracy'] is None
    (root / name).write_text('changed')
    with pytest.raises(ValueError, match='checksum'):
        module.evaluate(settings)
