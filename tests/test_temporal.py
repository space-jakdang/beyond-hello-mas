import pytest
from backend.tools.forecast import predict
from scripts.generate_temporal import generate
from eval.run_temporal import evaluate,metrics


def test_past_only_and_calendar_distance():
    past=[{'month':'2025-01','value':.1},{'month':'2025-03','value':.3},{'month':'2025-04','value':.4}]
    assert predict(past,'2025-05') == pytest.approx(.5)
    assert predict(past+[{'month':'2025-05','value':99},{'month':'2025-06','value':-99}],'2025-05') == predict(past,'2025-05')
    assert predict(past[:2],'2025-05') is None
    with pytest.raises(ValueError): predict(past+[past[0]],'2025-05')
    with pytest.raises(ValueError): predict([{'month':'2025-01','value':float('nan')}],'2025-05')


def test_temporal_reproducibility_and_real_holdout():
    rows=generate(17)
    assert len(rows)==47*8*12 and rows==generate(17) and rows!=generate(29)
    assert any(r['value'] is not None and r['value'] != r['truth'] for r in rows)
    a=evaluate((17,));b=evaluate((17,))
    assert a==b
    assert {r['month'] for r in a['by_month']}=={f'2025-{m:02}' for m in range(7,13)}
    assert a['overall']['trend']['count']==47*8*6
    assert a['overall']['trend']['coverage']<1


def test_missing_forecast_does_not_hide_missed_alert():
    m=metrics([{'prediction':None,'truth':.9},{'prediction':.8,'truth':.8}])
    assert m['alert_recall']==.5 and m['coverage']==.5 and m['mae']==0
