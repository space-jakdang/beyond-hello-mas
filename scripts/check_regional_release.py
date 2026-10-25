"""Offline acceptance of a private package with isolated disposable state (no paid calls)."""
import argparse
from datetime import date
import csv
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from uuid import uuid4
from zipfile import ZipFile

from backend.app.config import Settings
from backend.app.contracts import Scenario
from backend.events import EventStore
from backend.graph import GraphService
from backend.future import FutureRequest, create_batch, future_router
from backend.tools.regional_task import RegionalTask, assess, task_from
from backend.tools.neighborhoods import group_analysis, boundaries
from scripts.runtime_package import verify

REFERENCE_WEEK = date(2025, 12, 15)
REFERENCE_FIELDS = ('순위', '지역', '행정동', '성', '연령대', '틀', '단계명',
                    '카드경보', '최종단계', '최종단계명')
SEX = {'남': 'M', '여': 'F'}


def _optional_int(value):
    if not isinstance(value, str):
        raise ValueError('priority reference numeric field is invalid')
    value = value.strip()
    try:
        return int(value) if value else None
    except ValueError:
        raise ValueError('priority reference numeric field is invalid') from None


def _alarm_stage(value):
    try:
        return _optional_int(value)
    except ValueError:
        normalized = value.strip().casefold().replace(' ', '') if isinstance(value, str) else ''
        labels = {'-': 0, '없음': 0, '미발생': 0, '미경보': 0, '경보없음': 0, 'none': 0,
                  '약': 1, '약함': 1, '약한경보': 1, 'weak': 1,
                  '강': 2, '강함': 2, '강한경보': 2, 'strong': 2}
        if normalized not in labels:
            raise ValueError('priority reference card alarm is invalid') from None
        return labels[normalized]


def compare_priority_table(segments, path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(REFERENCE_FIELDS) <= set(reader.fieldnames):
            raise ValueError('priority reference columns do not match v4 contract')
        reference = {}
        for row in reader:
            if any(not isinstance(row.get(field), str) for field in REFERENCE_FIELDS):
                raise ValueError('priority reference contains an incomplete row')
            key = (row['지역'].strip(), row['행정동'].strip(), SEX.get(row['성'].strip()), row['연령대'].strip())
            if None in key or not all(key) or key in reference:
                raise ValueError('priority reference contains invalid or duplicate cells')
            reference[key] = row
    if len(reference) != len(segments):
        raise ValueError('priority reference cell count mismatch')
    fields = {'순위': 'priority_rank', '틀': 'frame', '단계명': 'source_stage_label',
              '최종단계명': 'final_stage_label'}
    mismatch = {}
    for segment in segments:
        key = (segment['source_region'], segment['source_dong_name'], segment['sex'], segment['source_age_band'])
        row = reference.pop(key, None)
        if row is None:
            mismatch['cell'] = mismatch.get('cell', 0) + 1
            continue
        for source, target in fields.items():
            if row[source].strip() != str(segment[target]):
                mismatch[source] = mismatch.get(source, 0) + 1
        # The source table keeps the -1/0 hold codes in this numeric column; the app carries status separately.
        final_stage = segment['final_stage'] if segment['final_stage'] is not None else segment['source_stage']
        for source, expected in (('카드경보', segment['card_alarm_stage']),
                                 ('최종단계', final_stage)):
            try:
                actual = _alarm_stage(row[source]) if source == '카드경보' else _optional_int(row[source])
            except ValueError:
                raise ValueError(f'priority reference {source} field is invalid') from None
            if actual != expected:
                mismatch[source] = mismatch.get(source, 0) + 1
    if reference or mismatch:
        if reference:
            mismatch['extra_reference_cells'] = len(reference)
        detail = ', '.join(f'{field}={count}' for field, count in sorted(mismatch.items())) or 'cell_count mismatch'
        raise ValueError('priority reference mismatch: ' + detail)
    return len(segments)


def _check_v2(root, source_delivery, before):
    if source_delivery is None:
        raise ValueError('v2 acceptance requires the original source delivery')
    from backend.tools.neighborhoods import group_analysis_v4
    from scripts.export_seohee_v4 import source_files, source_hashes

    source_root, paths = source_files(source_delivery)
    reference = source_root / '1_탐지/priority_1215.csv'
    if reference.is_symlink() or not reference.is_file():
        raise ValueError('2025-12-15 priority reference is unavailable')
    reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
    from backend.app.config import ROOT
    checked_paths = {**paths,
                     'data/geography/boundaries.geojson': ROOT / 'data/geography/boundaries.geojson',
                     'data/geography/manifest.json': ROOT / 'data/geography/manifest.json'}
    source_before = source_hashes(checked_paths)
    with tempfile.TemporaryDirectory(prefix='regional-v2-state-') as state:
        settings = Settings(_env_file=None, data_mode='local', input_root=root,
                            runtime_storage_root=Path(state), resource_catalog='v3',
                            regional_workflow_version='regional-workflow-2', llm_mode='fake',
                            person_mcp_mode='stub', openai_api_key=None,
                            gov24_service_key=None, kosis_api_key=None, llm_max_calls=10)
        results = []
        if (settings.openai_api_key is not None or settings.gov24_service_key is not None
                or settings.kosis_api_key is not None or settings.llm_mode != 'fake'
                or settings.person_mcp_mode != 'stub'):
            raise ValueError('offline acceptance must not inherit credentials or live mode')
        import_manifest = json.loads((settings.data_dir / 'import.json').read_text())
        if import_manifest.get('source_hashes') != source_before:
            raise ValueError('source delivery does not match the verified package')
        view = group_analysis_v4(settings, week=REFERENCE_WEEK.isoformat())
        segments = view['segments']
        if (view['metadata'].get('source', {}).get('synthetic') is not False
                or view['metadata'].get('dataset_version') != 'seohee-region-20261025-1'
                or view['metadata'].get('workflow_version') != 'regional-workflow-2'
                or len(segments) != before['summary']['segment_count']
                or len(view['weekly']['signals']) != before['summary']['card_signal_count']
                or view['metadata'].get('selected_week') != REFERENCE_WEEK.isoformat()):
            raise ValueError('v2 package did not produce the pinned observed analysis')
        matches = compare_priority_table(segments, reference)
        expected_statuses = before['summary']['status_counts']
        actual_statuses = {status: sum(row['assessment_status'] == status for row in segments)
                           for status in expected_statuses}
        if actual_statuses != expected_statuses or not any(actual_statuses.get(status, 0) for status in
                                                            ('small_population_hold', 'insufficient_evidence')):
            raise ValueError('v2 status denominators changed')
        for row in segments:
            if row['assessment_status'] != 'assessed' and row['final_stage'] is not None:
                raise ValueError('unassessed source stage became a final stage')

        service = GraphService(EventStore(settings.runtime_dir / 'events.sqlite3', settings.data_mode), settings)
        future_router(service)
        selections = [('11230', 'M', '20대'), ('11230', 'F', '70대+'),
                      ('32010', 'M', '30대'), ('32010', 'F', '60대+')]
        day = date(2026, 10, 25)
        run_ids = []
        for sgg, sex, preferred_age in selections:
            candidates = [row for row in segments if row['sgg'] == sgg and row['sex'] == sex
                          and row['assessment_status'] == 'assessed']
            if not candidates:
                raise ValueError(f'required regional baseline unavailable: {sgg}/{sex}')
            preferred = [row for row in candidates if row['source_age_band'] == preferred_age]
            row = sorted(preferred or candidates, key=lambda item: (item['source_age_band'], item['dong_cd']))[0]
            age = row['source_age_band']
            task = {'sgg': sgg, 'sex': sex, 'source_age_band': age,
                    'dong_cd': row['dong_cd'], 'as_of': day.isoformat(),
                    'card_week': REFERENCE_WEEK.isoformat()}
            scenario = Scenario(id=f'offline-v2-acceptance-{sgg}-{sex}', type='monthly',
                                sim_time=f'{day.isoformat()}T09:00:00+09:00',
                                payload={'workflow_version': 'regional-workflow-2', 'task': task,
                                         'policy_proposal_version': 'three-1', 'research_gaps': False})
            run = service.start(scenario)
            if run.status != 'awaiting_approval':
                raise ValueError('v2 regional flow did not reach human review')
            proposal = service.approval(run.id)['proposal']
            assessment = proposal['assessment']
            task_data = assessment.get('task', {})
            expected = {'sgg': sgg, 'sex': sex, 'source_age_band': age,
                        'dong_cd': row['dong_cd'], 'card_week': REFERENCE_WEEK.isoformat()}
            expected_assessment = assess(settings, task_from({'workflow_version': 'regional-workflow-2',
                                                              'task': task}), source_data=view)
            if (proposal.get('workflow_version') != 'regional-workflow-2'
                    or any(task_data.get(key) != value for key, value in expected.items())
                    or assessment.get('metadata', {}).get('selected_week') != REFERENCE_WEEK.isoformat()
                    or assessment.get('metadata', {}).get('input_hash') != expected_assessment['metadata']['input_hash']
                    or len(assessment.get('segments', [])) != 1
                    or assessment['segments'][0].get('dong_cd') != row['dong_cd']):
                raise ValueError('v2 proposal lost its pinned source scope')
            restored = GraphService(EventStore(settings.runtime_dir / 'events.sqlite3', settings.data_mode), settings)
            if restored.approval(run.id)['proposal'] != proposal:
                raise ValueError('v2 proposal changed across service instances')
            run_ids.append(run.id)
            results.append({'region': sgg, 'sex': sex, 'source_age_band': age,
                            'human_review_reached': True, 'proposal_preserved': True})
        for status in ('small_population_hold', 'insufficient_evidence'):
            row = next((item for item in segments if item['assessment_status'] == status), None)
            if row is None:
                raise ValueError('v2 package has no required unassessed status')
            task = task_from({'workflow_version': 'regional-workflow-2', 'task': {
                'sgg': row['sgg'], 'sex': row['sex'], 'source_age_band': row['source_age_band'],
                'dong_cd': row['dong_cd'], 'as_of': day.isoformat(),
                'card_week': REFERENCE_WEEK.isoformat()}})
            result = assess(settings, task, source_data=view)
            if (len(result['segments']) != 1 or result['segments'][0]['assessment_status'] != status
                    or result['segments'][0]['stage'] is not None):
                raise ValueError('v2 workflow changed a held or insufficient source cell')
        from fastapi.testclient import TestClient
        from backend.app.main import create_app
        with TestClient(create_app(settings)) as client:
            for run_id, result in zip(run_ids, results):
                response = client.get(f'/policy-proposals/{run_id}')
                if response.status_code != 200 or not response.json().get('sets'):
                    raise ValueError('v2 policy report data unavailable')
                proposal = response.json()['sets'][0]
                base = f"/policy-proposals/{run_id}/{proposal['dong_cd']}/download/"
                params = {'version': proposal['version'], 'revision': proposal['review_revision']}
                pdf = client.get(base + 'pdf', params=params)
                docx = client.get(base + 'docx', params=params)
                if pdf.status_code != 200 or not pdf.content.startswith(b'%PDF'):
                    raise ValueError('v2 PDF report export failed')
                if docx.status_code != 200 or not docx.content.startswith(b'PK'):
                    raise ValueError('v2 Word report export failed')
                with ZipFile(BytesIO(docx.content)) as archive:
                    report_text = archive.read('word/document.xml').decode()
                if (result['source_age_band'] not in report_text
                        or REFERENCE_WEEK.isoformat() not in report_text):
                    raise ValueError('v2 report lost its source age or pinned week')
        after = verify(root)
        if before != after or source_hashes(checked_paths) != source_before:
            raise ValueError('package or source delivery changed during acceptance')
        if hashlib.sha256(reference.read_bytes()).hexdigest() != reference_hash:
            raise ValueError('priority reference changed during acceptance')
    return {'check': 'offline-private-release-2', 'llm_mode': 'fake', 'external_api_tested': False,
            'dataset_version': before['dataset_version'], 'workflow_version': before['workflow_version'],
            'observed_period': before['summary']['observed_period'],
            'segment_cells_checked': matches, 'card_signals_checked': len(view['weekly']['signals']),
            'priority_reference_week': REFERENCE_WEEK.isoformat(), 'status_counts': actual_statuses,
            'boundaries': before['summary']['boundary_matches'], 'workflows': results,
            'report_exports_checked': len(run_ids) * 2,
            'checked_sources_and_package_unchanged': True, 'state': 'disposable_local_only',
            'permission_status': before['provenance']['permission_status'],
            'not_verified': ['clinical_accuracy', 'live_api', 'production_restart', 'host_mount_tls_auth']}


def check(root, source_delivery=None):
    root = Path(root).absolute()
    before = verify(root)
    if before['version'] == 2:
        return _check_v2(root, source_delivery, before)
    results = []
    with tempfile.TemporaryDirectory(prefix='regional-acceptance-') as state:
        settings = Settings(_env_file=None, data_mode='local', input_root=root,
                            runtime_storage_root=Path(state), resource_catalog='v3',
                            llm_mode='fake', person_mcp_mode='stub', openai_api_key=None,
                            llm_max_calls=10, **{'GOV24_API_KEY': None})
        if settings.openai_api_key is not None or settings.gov24_service_key is not None or settings.llm_mode != 'fake' or settings.person_mcp_mode != 'stub':
            raise ValueError('offline acceptance must not inherit credentials or live mode')
        view = group_analysis(settings, week='all', card_age='all')
        if view['coverage']['unmatched_codes']:
            raise ValueError('unmatched real geography')
        expected = {f['properties']['dong_cd'] for f in boundaries()[0]['features']}
        if {r['dong_cd'] for r in view['neighborhoods']} != expected:
            raise ValueError('package does not cover all supplied neighborhood boundaries')
        preserved = {}
        service = GraphService(EventStore(settings.runtime_dir/'events.sqlite3', settings.data_mode), settings)
        future_router(service)
        day = date.today()
        for sgg in ('11230', '32010'):
            candidates = [r for r in view['segments'] if r['sgg'] == sgg and r['preferred']
                          and r['sex'] == 'M' and r['age_group'] == 'youth']
            if not candidates:
                raise ValueError('required regional baseline unavailable')
            row = sorted(candidates, key=lambda r: (r['dong_cd'], r['ym'] or ''))[-1]
            task = RegionalTask(sgg=sgg, dong_cd=row['dong_cd'], sex='M', age_group='youth',
                                ym=row['ym'] or day.strftime('%Y-%m'), as_of=day)
            scenario = Scenario(id=f'offline-private-acceptance-{sgg}', type='monthly',
                                sim_time=f'{day.isoformat()}T09:00:00+09:00',
                                payload={'workflow_version':'regional-workflow-1',
                                         'statistics_version':'2', 'policy_proposal_version':'three-1',
                                         'research_gaps':False, 'task':task.model_dump(mode='json')})
            run = service.start(scenario)
            if run.status != 'awaiting_approval':
                raise ValueError('regional flow did not reach human review')
            proposal = service.approval(run.id)
            preserved[run.id] = proposal
            if service.store.get_run(run.id).status != 'awaiting_approval':
                raise ValueError('proposal read unexpectedly advanced review')
            observed = assess(settings, task)
            saved = proposal['proposal']['assessment']
            if not saved['segments'] or saved['task'] != task.model_dump(mode='json') or saved['metadata']['input_hash'] != observed['metadata']['input_hash']:
                raise ValueError('workflow lost the requested input scope')
            restored = GraphService(EventStore(settings.runtime_dir/'events.sqlite3', settings.data_mode), settings)
            if restored.approval(run.id) != proposal:
                raise ValueError('stored proposal changed across service instances')
            future = create_batch(service, FutureRequest(request_id=uuid4(), sgg=sgg))
            future_task = RegionalTask(future_id=future['id'], sgg=sgg, sex='M', age_group='youth',
                                      ym=future['months'][0], as_of=future['as_of'])
            derived = assess(settings, future_task)
            if not derived['metadata']['synthetic_future']:
                raise ValueError('future scenario lost synthetic identity')
            if assess(settings, task)['metadata']['synthetic_future']:
                raise ValueError('observed input contaminated by future scenario')
            with service.store.connection() as db:
                if db.execute('SELECT count(*) FROM linkages').fetchone()[0]:
                    raise ValueError('offline check unexpectedly linked a resource')
            results.append({'sgg':sgg, 'human_review_reached':True,
                            'proposal_preserved':True, 'future_isolated':True})
        restored = GraphService(EventStore(settings.runtime_dir/'events.sqlite3', settings.data_mode), settings)
        if any(restored.approval(identifier) != proposal for identifier, proposal in preserved.items()):
            raise ValueError('another region changed a stored proposal')
        after = verify(root)
        if before != after:
            raise ValueError('input package changed during acceptance')
    return {'check':'offline-private-release-1', 'llm_mode':'fake', 'external_api_tested':False,
            'neighborhoods':view['coverage']['matched'], 'regions':results,
            'input_unchanged':True, 'state':'disposable',
            'not_verified':['live_api', 'policy_quality', 'production_restart', 'ux_m_integration']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--source-delivery', type=Path,
                        help='original 2026-10-25 delivery folder required for private v2 source checks')
    args = parser.parse_args()
    print(json.dumps(check(args.root, args.source_delivery), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
