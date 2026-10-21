"""Read-only readiness views. Private judgments never leave the evaluation store."""
import json
from uuid import UUID
from fastapi import HTTPException
from backend.app import config
from eval.quality_contracts import load_frozen, readiness_report
from eval.quality_metrics import classification
from eval.grounding_contracts import load_grounding
from eval.quality_matching import matching
from eval.quality_study import load_study


def quality_root(settings, source):
    mode = 'sample' if source == 'sample' else settings.data_mode
    return config.ROOT / 'runtime' / 'quality' / mode


def quality_detail(settings, source, report_id, region=None, period=None, methodology=None):
    root = quality_root(settings, source)
    folder = root / str(report_id)
    if not folder.is_dir() or folder.resolve().parent != root.resolve():
        raise HTTPException(404, 'quality report not found')
    try:
        paths = [folder / name for name in ('inputs.json', 'labels.json')]
        if any(p.is_symlink() for p in paths):
            raise ValueError('symlink not allowed')
        frozen, labels = [json.loads(p.read_text()) for p in paths]
        dataset = load_frozen(frozen)
        if root.name == 'sample' and any(c.source != 'synthetic' for c in dataset.cases):
            raise ValueError('observed inputs in sample store')
        report = readiness_report(frozen, labels)
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        raise HTTPException(409, 'quality report incomplete or invalid')
    cases = [c for c in dataset.cases if (not region or c.region == region)
        and (not period or c.period == period) and (not methodology or c.methodology == methodology)]
    ids = {c.id for c in cases}
    scores = None
    grounding = None
    resource_scores = None
    prediction_path = folder / 'predictions.json'
    if prediction_path.exists() or prediction_path.is_symlink():
        try:
            if prediction_path.is_symlink():raise ValueError('symlink not allowed')
            predictions = json.loads(prediction_path.read_text())
            scores = classification(frozen, labels, predictions, ids)
            resource_scores = matching(frozen, labels, predictions, ids)
            grounding = load_grounding(folder, frozen, predictions, ids)
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            raise HTTPException(409, 'quality predictions incomplete or invalid')
    try:
        study=load_study(folder,frozen,labels,ids)
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        raise HTTPException(409, 'quality study incomplete or invalid')
    refs = [r for r in report['references'] if r['case_id'] in ids]
    counts = {state: sum(r['state'] == state for r in refs) for state in ('missing', 'unknown', 'disagreement', 'resolved')}
    return {'id': str(report_id), 'schema_version': '6', 'dataset': dataset.id, 'version': dataset.version,
        'dataset_hash': report['dataset_hash'], 'label_hash': report['label_hash'],
        'data_mode': root.name, 'status': 'partial' if (scores and any(g['reference_count'] for g in scores['groups'])) or (resource_scores and any(r['judged_count'] for r in resource_scores['rows'])) or (grounding and grounding['rows']) or (study and any(a['classification']['reference_count'] for g in study['groups'] for a in g['arms'])) else 'not_evaluated', 'metrics': None,
        'model': scores['model'] if scores else None, 'execution_status': 'predictions_imported' if scores else 'not_run',
        'classification': scores, 'matching': resource_scores, 'study':study, 'grounding': grounding,
        'filters': {field: sorted({getattr(c, field) for c in dataset.cases}) for field in ('region', 'period', 'methodology', 'source')},
        'readiness': {'cases': len(cases), 'reference_items': len(refs), **counts,
            'independent_resolved': sum(r['independent'] and r['state'] == 'resolved' for r in refs)},
        'cases': [{'id': c.id, 'region': c.region, 'neighborhood': c.neighborhood, 'period': c.period,
            'methodology': c.methodology, 'source': c.source,
            'references': [{k: r[k] for k in ('policy_id', 'state', 'independent', 'review_count', 'adjudicated', 'provenance')}
                for r in refs if r['case_id'] == c.id]} for c in cases],
        'limitations': ['분류 점수는 독립 참조와 예측이 모두 있는 범위만 계산하며 다른 평가 축을 대신하지 않습니다.',
            '합성 입력에 대한 독립 평정도 실제 지역 성능을 입증하지 않습니다.']}


def quality_list(settings, source):
    root = quality_root(settings, source)
    rows = []
    for folder in sorted(root.glob('*'), reverse=True):
        try:
            report_id = UUID(folder.name)
        except ValueError:
            continue
        try:
            body = quality_detail(settings, source, report_id)
            rows.append({k: body[k] for k in ('id', 'dataset', 'version', 'status', 'data_mode', 'readiness')})
        except HTTPException as error:
            if error.status_code == 409:
                rows.append({'id': str(report_id), 'status': 'failed', 'dataset': '손상된 평가 자료', 'version': '',
                    'data_mode': root.name, 'readiness': None})
    return rows
