"""One-month synthetic signal baselines. Never estimates an individual's isolation."""
import math
from datetime import date


def predict(history, target_month, method='trend'):
    if method not in ('trend', 'last_value'):
        raise ValueError('unknown forecast method')
    target = date.fromisoformat(target_month + '-01')
    values = []
    seen = set()
    for row in history:
        month = date.fromisoformat(row['month'] + '-01')
        if month in seen:
            raise ValueError('duplicate observation month')
        seen.add(month)
        # Future rows are ignored before their values are inspected.
        if month >= target:
            continue
        value = row['value']
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('signal must be finite and between zero and one')
        values.append((month.year * 12 + month.month, value))
    values.sort()
    if len(values) < 3:
        return None
    recent = values[-3:]
    if method == 'last_value':
        return recent[-1][1]
    xmean = sum(x for x, _ in recent) / 3
    ymean = sum(y for _, y in recent) / 3
    slope = sum((x-xmean)*(y-ymean) for x,y in recent) / sum((x-xmean)**2 for x,_ in recent)
    return max(0., min(1., ymean + slope*(target.year*12+target.month-xmean)))
