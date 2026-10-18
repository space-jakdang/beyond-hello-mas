import random
from pathlib import Path

import pandas as pd
import pytest

from backend.app.config import Settings
from backend.app.contracts import Segment
from backend.tools.indicators import Indicator, Rules, default_rules, ratio
from backend.tools.segments import load_segments, validate, write_segments
from backend.tools.staging import classify
from scripts.export_segments import fingerprint, load_flow
from scripts.generate_segments import generate


def small(values):
    base = generate()[0]
    return [base.model_copy(update={'dong_cd': f'11230{i:03}', 'indicators': {name: v for name in ('a', 'b', 'c')}})
            for i, v in enumerate(values)]


def rules():
    return Rules(indicators=[Indicator(name=name, direction='higher', minimum=0, maximum=10,
                                      spatial_unit='dong_age') for name in ('a', 'b', 'c')])


def test_sample_reproducible_complete_and_order_independent():
    rows = generate()
    assert rows == generate()
    assert len(rows) == 1692
    _, coverage = validate(rows, complete=True)
    assert coverage['missing_keys'] == []
    first = classify(rows)
    for seed in (1, 2):
        shuffled = rows.copy()
        random.Random(seed).shuffle(shuffled)
        assert classify(shuffled) == first
    with pytest.raises(ValueError, match='duplicate'):
        validate(rows + [rows[0]])
    with pytest.raises(ValueError, match='complete sample'):
        validate(rows[:-1], complete=True)


def test_hand_calculation_ties_constants_missing_and_limits():
    # Mean 1, population SD 1. Every component is -1 or +1, so mean score is -1/+1.
    result = classify(small([0, 2]), rules())['segments']
    assert [r['score'] for r in result] == [-1, 1]
    assert [r['stage'] for r in result] == [2, 4]
    result = classify(small([1, 1, 1]), rules())['segments']
    assert [(r['score'], r['stage'], r['rank']) for r in result] == [(0, 3, 1)] * 3
    result = classify(small([None, 11, 1]), rules())['segments']
    assert [r['stage'] for r in result] == [None, None, 3]
    assert ratio(1, 0) is None and ratio(1, None) is None and ratio(2, 4) == 0.5
    assert ratio(float('nan'), 2) is None


def test_missing_month_not_compared_and_dong_summary():
    first = small([1])[0]
    rows = [first, first.model_copy(update={'ym': '2025-09'})]
    report = classify(rows, rules())
    assert '2025-08' in report['metadata']['missing_months']
    assert report['segments'][1]['score_change'] is None
    assert report['dongs'][0]['missing_age_count'] == 5
    rows.append(first.model_copy(update={'ym': '2025-10', 'indicators': {'a': 2, 'b': 2, 'c': 2}}))
    assert classify(rows, rules())['segments'][-1]['change_flag']


def test_parquet_round_trip_and_no_fallback(tmp_path, monkeypatch):
    import backend.app.config as config
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    with pytest.raises(FileNotFoundError):
        load_segments(Settings(_env_file=None, data_mode='local'))
    path = tmp_path / 'data/sample/segments.parquet'
    write_segments(path, generate(), {'data_mode': 'sample', 'seed': 42})
    rows, metadata = load_segments(Settings(_env_file=None, data_mode='sample'))
    assert rows == sorted(generate(), key=lambda r: (r.ym, r.dong_cd, r.age_band))
    assert metadata['seed'] == 42
    wrong = tmp_path / 'data/local/segments.parquet'
    wrong.parent.mkdir()
    wrong.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match='mode'):
        load_segments(Settings(_env_file=None, data_mode='local'))


def test_export_deduplicates_exact_rows_but_keeps_coordinate_cells(tmp_path):
    path = tmp_path / 'flow_time_pop_202512.csv'
    frame = pd.DataFrame([{'BLOCK_CD': '1123074000', 'STD_YM': '202512', 'X_COORD': x,
                           'Y_COORD': 2, 'value': 4} for x in [1, 1, 3]])
    frame.to_csv(path, sep='|', index=False)
    before = fingerprint(path)
    result = load_flow([path])
    assert len(result) == 2 and set(result.dong) == {'11230511'}
    assert fingerprint(path) == before
    frame.loc[1, 'value'] = 5
    frame.to_csv(path, sep='|', index=False)
    with pytest.raises(ValueError, match='conflicting'):
        load_flow([path])


def test_rules_validate_and_hash_changes():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Rules(indicators=[default_rules().indicators[0]] * 3)
    changed = rules().model_copy(update={'version': 'provisional-2'})
    assert classify(small([1]), rules())['metadata']['rule_hash'] != classify(small([1]), changed)['metadata']['rule_hash']


def test_source_missing_values_are_not_summed_as_zero(tmp_path):
    path = tmp_path / 'age.csv'
    pd.DataFrame([{'BLOCK_CD': '1123051100', 'STD_YM': '202507', 'X_COORD': 1,
                   'Y_COORD': 2, 'value': None}]).to_csv(path, sep='|', index=False)
    with pytest.raises(ValueError, match='numeric source'):
        load_flow([path])


def test_sample_preserves_all_age_indicator_scope():
    from collections import defaultdict
    groups = defaultdict(list)
    for row in generate():
        groups[(row.ym, row.dong_cd)].append(row)
    for rows in groups.values():
        assert sum(r.indicators['age_share'] for r in rows) == pytest.approx(1)
        assert len({r.indicators['night_share'] for r in rows}) == 1
