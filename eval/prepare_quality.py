"""Prepare private quality evaluation artifacts without calling any model."""
import argparse
import csv
import json
from pathlib import Path
from uuid import uuid4
from eval.quality_contracts import freeze, load_frozen, readiness_report, blind_packet, unblind_judgments


def read_judgments(path):
    if path.suffix.lower() != '.csv':
        return json.loads(path.read_text())
    with path.open(newline='') as file:
        reader = csv.DictReader(file)
        required = {'case_id', 'policy_id', 'reviewer', 'value', 'reason', 'reviewed_at', 'provenance', 'policy_as_of', 'adjudication'}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError('CSV missing columns: ' + ', '.join(sorted(missing)))
        rows = list(reader)
    for row in rows:
        row['policy_id'] = row['policy_id'] or None
        if row['adjudication'] not in ('true', 'false'):
            raise ValueError('CSV adjudication must be true or false')
        row['adjudication'] = row['adjudication'] == 'true'
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--labels', type=Path, help='JSON reviewers and judgments bound to dataset_hash')
    parser.add_argument('--judgments', type=Path, help='CSV/JSON judgments replacing labels judgments')
    parser.add_argument('--predictions', type=Path, help='Frozen-dataset-bound model predictions JSON')
    parser.add_argument('--policy-candidates',type=Path,help='Separate max5 government-policy predictions')
    parser.add_argument('--policy-drafts',type=Path,help='Frozen dataset-bound draft reports')
    parser.add_argument('--policy-draft-ratings',type=Path,help='Independent rubric ratings bound to draft input hash')
    parser.add_argument('--key', type=Path, help='Private map for blind case IDs in supplied judgments')
    parser.add_argument('--output-root', type=Path, default=None)
    args = parser.parse_args()
    if args.judgments and not args.labels:
        parser.error('--judgments requires --labels reviewer metadata')
    body = json.loads(args.dataset.read_text())
    if 'schema_version' in body:
        load_frozen(body)
        frozen = body
    else:
        frozen = freeze(body)
    labels = json.loads(args.labels.read_text()) if args.labels else {
        'dataset_hash': frozen['dataset_hash'], 'reviewers': [], 'judgments': []}
    if args.judgments:
        labels['judgments'] = read_judgments(args.judgments)
    if args.key:
        if not args.labels:
            parser.error('--key requires --labels')
        imported_key = json.loads(args.key.read_text())
        labels['judgments'] = unblind_judgments(frozen, imported_key, labels['judgments'])
    report = readiness_report(frozen, labels)
    predicted = None
    if args.predictions:
        from eval.quality_metrics import validate_predictions
        predicted = validate_predictions(frozen, json.loads(args.predictions.read_text())).model_dump()
    extras = [('import-key', imported_key)] if args.key else list(zip(('blind-packet', 'private-key'), blind_packet(frozen)))
    if predicted is not None:extras.append(('predictions', predicted))
    if args.policy_candidates:
        from eval.quality_metrics import validate_predictions
        extras.append(('policy-candidates',validate_predictions(frozen,json.loads(args.policy_candidates.read_text()),True).model_dump()))
    if args.policy_draft_ratings and not args.policy_drafts:parser.error('--policy-draft-ratings requires --policy-drafts')
    if args.policy_drafts:
        from eval.policy_design_quality import quality
        drafts=json.loads(args.policy_drafts.read_text());ratings=json.loads(args.policy_draft_ratings.read_text()) if args.policy_draft_ratings else None
        quality(frozen,drafts,ratings);extras.append(('policy-drafts',drafts))
        if ratings:extras.append(('policy-draft-ratings',ratings))
    mode = 'sample' if all(c['source'] == 'synthetic' for c in frozen['dataset']['cases']) else 'local'
    folder = (args.output_root or Path('runtime/quality') / mode) / str(uuid4())
    folder.mkdir(parents=True, exist_ok=False)
    for name, value in [('inputs', frozen), ('labels', labels), ('readiness', report)] + extras:
        (folder / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(folder)


if __name__ == '__main__':
    main()
