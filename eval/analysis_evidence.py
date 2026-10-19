"""Read-only source lineage and sensitivity checks; no isolation accuracy labels."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean, median, stdev
from uuid import uuid4

from backend.app.config import ROOT, Settings
from backend.tools.indicators import digest
from backend.tools.region_stage import classify, level_band, youth_stage
from backend.tools.segments_v3 import load_segments
from backend.tools.weekly_signals import alarm, load as load_weekly
from scripts.import_seohee import inventory


def weekly_sensitivity(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['sgg'], row['sex'], row['age_band'])].append(row)
    result = []
    for window, statistic in ((6, 'median'), (8, 'median'), (10, 'median'), (8, 'mean')):
        changed = compared = unavailable = 0
        for key, group in sorted(groups.items()):
            group = sorted(group, key=lambda r: r['week'])
            weak = .90 if key == ('32010', 'F', '20s') else .95
            for indicator in ('T1b', 'R1'):
                history = []; ratios = []; reference = []
                for row in group:
                    metric = row['metrics'][indicator]
                    prior = history[-window:]
                    baseline = (median(prior) if statistic == 'median' else mean(prior)) if len(prior) == window else None
                    ratios.append(metric['value'] / baseline if baseline else None)
                    reference.append(metric['value'] / metric['baseline'] if metric['baseline'] else None)
                    # Compare only when both windows have observations; retain excluded count.
                    if ratios[-1] is None or reference[-1] is None:
                        unavailable += 1
                    else:
                        compared += 1
                        changed += alarm(ratios, weak) != alarm(reference, weak)
                    history.append(metric['value'])
        result.append({'window': window, 'statistic': statistic, 'changed_alerts': changed,
                       'compared_alerts': compared, 'unavailable_alerts': unavailable})
    return result


def weight_sensitivity(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.index_name == 'G_chuncheon' and row.preferred:
            groups[(row.ym, row.sex, row.age_group)].append(row)
    result = []
    for key, group in sorted(groups.items(), key=lambda x: str(x[0])):
        if any(not {'structure', 'visibility_risk'} <= set(r.components) for r in group):
            result.append({'group': key, 'status': 'missing_components'}); continue
        branches = []
        for field in ('structure', 'visibility_risk'):
            values = [r.components[field] for r in group]
            spread = stdev(values) if len(values) > 1 else 0
            if not spread:
                break
            branches.append([(v - mean(values)) / spread for v in values])
        if len(branches) != 2:
            result.append({'group': key, 'status': 'constant_or_insufficient_components'}); continue
        def order(weight):
            scores = [weight * a + (1 - weight) * b for a, b in zip(*branches)]
            return sorted(range(len(group)), key=lambda i: (-scores[i], group[i].dong_cd))
        original = order(.7); positions = {i: rank for rank, i in enumerate(original)}
        for weight in (.6, .7, .8):
            alternative = order(weight)
            pairs = [(a, b) for rank, a in enumerate(alternative) for b in alternative[rank + 1:]]
            result.append({'group': key, 'structure_weight': weight, 'status': 'evaluated',
                           'reversed_pairs': sum(positions[a] > positions[b] for a, b in pairs),
                           'compared_pairs': len(pairs),
                           'max_rank_shift': max(abs(rank - positions[i]) for rank, i in enumerate(alternative))})
    return result


def evaluate(settings):
    rows, metadata = load_segments(settings); weekly = load_weekly(settings)
    source_hashes = {}
    if settings.data_mode == 'local':
        root = settings.data_dir / 'seohee'
        manifest = json.loads((root / 'import.json').read_text())['files']
        actual = inventory(root); actual.pop('import.json', None)
        if actual != manifest:
            raise ValueError('source bundle checksum mismatch')
        for name, checksum in manifest.items():
            basename = Path(name).name
            if basename in source_hashes:
                raise ValueError('ambiguous source basename')
            source_hashes[basename] = checksum
    lineage = {}
    for row in rows:
        key = (row.source_file, row.index_name, row.age_group, row.sex, row.preferred, row.source_period)
        if settings.data_mode == 'local' and row.source_file not in source_hashes:
            raise ValueError('unregistered source')
        entry = lineage.setdefault(key, {'source_file': row.source_file, 'source_sha256': source_hashes.get(row.source_file),
            'index': row.index_name, 'age_group': row.age_group, 'sex': row.sex, 'preferred': row.preferred,
            'spatial_unit': 'dong_group', 'source_period': row.source_period, 'source_bands': row.source_bands,
            'months': set(), 'rows': 0, 'missing_values': 0})
        if (entry['source_period'], entry['source_bands']) != (row.source_period, row.source_bands):
            raise ValueError('inconsistent source lineage')
        entry['months'].add(row.ym); entry['rows'] += 1; entry['missing_values'] += row.value is None
    for entry in lineage.values():
        entry['months'] = sorted(entry['months'], key=lambda v: v or '')
    youth = [r for r in rows if r.preferred and r.index_name in ('S1', 'v3') and r.value is not None]
    thresholds = [{'absolute_value_shift': shift, 'changed_stages': sum(
        youth_stage(level_band(r.index_name, r.value + shift)) != youth_stage(level_band(r.index_name, r.value)) for r in youth),
        'compared_cohorts': len(youth)} for shift in (-.01, 0, .01)]
    missing = classify([r.model_copy(update={'value': None}) for r in rows])
    files = ['eval/analysis_evidence.py', 'scripts/export_groups.py', 'backend/tools/region_stage.py',
             'backend/tools/segments_v3.py', 'backend/tools/weekly_signals.py', 'rules/age_crosswalk.json']
    return {'schema_version': 'analysis-evidence-1', 'data_mode': settings.data_mode,
        'input_hash': metadata['input_hash'], 'weekly_input_hash': digest(weekly['rows']),
        'code_hash': digest({f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files}),
        'lineage': list(lineage.values()), 'weekly_source': weekly['metadata'],
        'weekly_sensitivity': weekly_sensitivity(weekly['rows']), 'youth_threshold_sensitivity': thresholds,
        'chuncheon_weight_sensitivity': weight_sensitivity(rows),
        'missingness': {'tested_cohorts': len(rows), 'unclassified_when_missing': sum(r['stage'] is None for r in missing['segments'])},
        'actual_isolation_accuracy': None, 'external_person_model_performance': None,
        'limitations': ['Source hashes identify delivered aggregates, not independent reconstruction from provider raw data.',
            'Sensitivity is a perturbation check, not parameter tuning or prediction accuracy.',
            'Weekly signals are district/sex/10-year-age observations, not dong observations.',
            'Youth threshold changes exclude weekly signals; non-youth provided stages are preserved.',
            'Weight ranks use dong code to break ties; comparisons are within each cohort only.',
            'Alternative explanations (seasonality, commerce, academic calendar) remain unverified hypotheses.']}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--local', action='store_true'); args = parser.parse_args()
    settings = Settings(_env_file=None, data_mode='local' if args.local else 'sample', llm_mode='fake')
    result = evaluate(settings)
    folder = settings.runtime_dir / 'analysis-evidence' / str(uuid4()); folder.mkdir(parents=True)
    result['created_at'] = datetime.now(timezone.utc).isoformat()
    (folder / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(folder.relative_to(ROOT))


if __name__ == '__main__':
    main()
