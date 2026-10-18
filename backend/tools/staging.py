from collections import defaultdict
from math import fsum
from statistics import mean, pstdev

from backend.tools.indicators import default_rules, digest
from backend.tools.segments import validate


def classify(rows, rules=None):
    rules = rules or default_rules()
    rows, coverage = validate(rows)
    # Fit one reference across all supplied months; stages use each month's cohort.
    columns = {}
    for indicator in rules.indicators:
        values = [r.indicators.get(indicator.name) for r in rows]
        valid = [v for v in values if v is not None and indicator.minimum <= v <= indicator.maximum]
        center, spread = (mean(valid), pstdev(valid)) if valid else (0, 0)
        columns[indicator.name] = (center, spread)
    results = []
    for row in rows:
        components, missing = {}, []
        for indicator in rules.indicators:
            value = row.indicators.get(indicator.name)
            if value is None or not indicator.minimum <= value <= indicator.maximum:
                missing.append(indicator.name)
                continue
            center, spread = columns[indicator.name]
            z = (value - center) / spread if spread else 0.0
            components[indicator.name] = z if indicator.direction == 'higher' else -z
        results.append({'ym': row.ym, 'dong_cd': row.dong_cd, 'age_band': row.age_band,
                        'score': None if missing else fsum(components.values()) / len(rules.indicators),
                        'components': components, 'missing': missing, 'blind_flag': row.blind_flag,
                        'stage': None, 'rank': None, 'score_change': None, 'change_flag': False})
    months = defaultdict(list)
    for result in results:
        months[result['ym']].append(result)
    for cohort in months.values():
        scores = sorted(r['score'] for r in cohort if r['score'] is not None)
        for result in cohort:
            score = result['score']
            if score is None:
                continue
            lower = sum(v < score for v in scores)
            equal = scores.count(score)
            # Midrank: ties share a stage; a constant cohort is stage 3, not forced quintiles.
            percentile = (lower + equal / 2) / len(scores)
            result['stage'] = min(5, int(percentile * 5) + 1)
            result['rank'] = 1 + sum(v > score for v in scores)
    previous = {}
    for result in results:
        k = result['dong_cd'], result['age_band']
        last = previous.get(k)
        if (last and int(result['ym'][-2:]) == int(last['ym'][-2:]) + 1
                and last['score'] is not None and result['score'] is not None):
            result['score_change'] = result['score'] - last['score']
            result['change_flag'] = abs(result['score_change']) >= rules.change_threshold
        previous[k] = result
    groups = defaultdict(list)
    for result in results:
        groups[(result['ym'], result['dong_cd'])].append(result)
    summaries = []
    for (month, dong), group in sorted(groups.items()):
        stages = [r['stage'] for r in group if r['stage'] is not None]
        summaries.append({'ym': month, 'dong_cd': dong, 'stage': max(stages, default=None),
                          'missing_age_count': 6 - len(stages), 'ages': group})
    return {'metadata': {'rule_version': rules.version, 'rule_hash': digest(rules.model_dump(mode='json')),
                         'input_hash': digest([r.model_dump(mode='json') for r in rows]),
                         'provisional': True, 'normalization': 'population z-score; all input months',
                         'staging': 'monthly midrank quintiles; ties preserved',
                         'spatial_units': {i.name: i.spatial_unit for i in rules.indicators},
                         'card_note': 'district×age values, when selected, are copied to dongs; not dong observations',
                         **coverage}, 'segments': results, 'dongs': summaries}
