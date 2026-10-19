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
    from statistics import median
    rows = rows[:23]
    values = [3,3,1,1,1,1,1,1,.94,.94,1,1] + [1]*11
    for i,row in enumerate(rows):
        for metric in row['metrics'].values():
            metric.update(value=values[i], baseline=median(values[i-8:i]) if i>=8 else None)
    changed = weekly_sensitivity(rows)
    # At week 10 the median signals weak while the mean signals strong, for both metrics.
    assert changed[3]['changed_alerts'] == 2
    assert changed[1]['changed_alerts'] == 0


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
    row = generate()[0].model_copy(update={'source_file': name})
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


def test_weight_change_can_reverse_a_pair():
    rows = [r for r in generate() if r.index_name == 'G_chuncheon'][:4]
    structure = [.63,.79,.09,.30]; visibility = [.09,.81,.69,.04]
    rows = [r.model_copy(update={'ym':'2025-07','sex':'M','age_group':'midlife','dong_cd':str(i),'preferred':True,
        'components':{'structure':structure[i],'visibility_risk':visibility[i]}}) for i,r in enumerate(rows)]
    result = weight_sensitivity(rows)
    assert result[1]['is_baseline'] and result[1]['reversed_pairs'] == 0
    assert result[2]['reversed_pairs'] == result[2]['max_rank_shift'] == 1
