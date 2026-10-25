import csv
import base64
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tools.neighborhoods import boundaries
from backend.tools import card_alarm_v4, segments_v4
from backend.tools.indicators import digest
from scripts.runtime_package import (
    FILES_V2, build, encode, settings_from_package, verify,
)
from tests.test_runtime_package import PROVENANCE, create_source


def v2_source(root):
    local = root / 'local'
    local.mkdir(parents=True)
    geography, geography_metadata = boundaries()
    rows = []
    for feature in geography['features']:
        props = feature['properties']
        region = '강남' if props['region_name'] == '강남구' else '춘천'
        for age_index, age in enumerate(segments_v4.SOURCE_AGE_BANDS[region]):
            stage = (-1, 0, 1, 2, 3, 5)[age_index]
            for sex in ('M', 'F'):
                rows.append(segments_v4.SegmentV4(
                    source_region=region, sgg=props['sgg'], dong_cd=props['dong_cd'],
                    dong_nm=props['dong_nm'], source_dong_name=props['dong_nm'], sex=sex,
                    source_age_band=age, frame=segments_v4.FRAME_BY_AGE[age],
                    source_bands={'dong_stage_age': [age]}, source_stage=stage,
                    source_stage_label=segments_v4.STAGE_LABEL[stage],
                    assessment_status='insufficient_evidence' if stage == -1 else
                                      'small_population_hold' if stage == 0 else 'assessed',
                    base_stage=stage if stage > 0 else None, weakness_count=1, reason='합성 fixture',
                    population=500,
                    structural_risk_ratio=1.2 if region == '강남' and age in ('40대', '50대', '60대', '70대+') else None,
                ))
    segment_path = local / 'segments-v4.parquet'
    source_hashes = {
        name: hashlib.sha256(f'synthetic:{name}'.encode()).hexdigest()
        for name in (
            '1_탐지/dong_stage_age.csv', '1_탐지/structural_risk_seoul.csv',
            '1_탐지/card_alarm_weekly.csv', 'data/geography/boundaries.geojson',
            'data/geography/manifest.json',
        )
    }
    segment_metadata = segments_v4.write_segments(segment_path, rows, 'local', source_hashes)
    card_path = local / 'seohee/card_alarm_weekly.csv'
    card_path.parent.mkdir(parents=True)
    fields = list(card_alarm_v4.FIELDS)
    weeks = [date(2025, 1, 6) + timedelta(days=7 * index) for index in range(22)]
    with card_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for region in ('강남', '춘천'):
            for sex in ('M', 'F'):
                for age in card_alarm_v4.CARD_AGE_BANDS:
                    for week in weeks:
                        writer.writerow({
                            '지역': region, '성': '남' if sex == 'M' else '여', '연령대': age,
                            '주': week.strftime('%m/%d'), 'V배': '1.00', 'N배': '1.00',
                            'V단계': '1', 'N단계': '1', '경보': '1', '약기준': '0.95', '강기준': '0.90',
                        })
    (local / 'import.json').write_text(json.dumps({
        'manifest_version': '1', 'generator': 'scripts.export_seohee_v4:1',
        'input_schema_version': 4, 'observation_year': 2025, 'local_only': True,
        'dataset_version': segments_v4.DATASET_VERSION, 'data_mode': 'local',
        'geography_version': geography_metadata['version'],
        'geography_hash': geography_metadata['subset_sha256'],
        'source_hashes': source_hashes, 'input_hash': digest(source_hashes),
        'segment_input_hash': segment_metadata['input_hash'],
        'artifact_hashes': {
            'segments-v4.parquet': hashlib.sha256(segment_path.read_bytes()).hexdigest(),
            'seohee/card_alarm_weekly.csv': hashlib.sha256(card_path.read_bytes()).hexdigest(),
        },
    }))
    (local / 'private-row-level.csv').write_text('must not be packaged')
    return root


@pytest.fixture
def catalog_package(tmp_path):
    package = tmp_path / 'v1'
    build(create_source(tmp_path/'v1-source'), package,
          {**PROVENANCE, 'permission_status': 'private_contest_use_confirmed'})
    return package


@pytest.fixture
def v2_package(catalog_package, tmp_path):
    package = tmp_path / 'v2'
    build(v2_source(tmp_path / 'v4-source'), package,
          {**PROVENANCE, 'permission_status': 'private_contest_use_confirmed'},
          package_version=2, catalog_from_package=catalog_package)
    return package


def test_v2_package_roundtrips_and_selects_matching_workflow(v2_package, tmp_path):
    from scripts.runtime_package import restore

    manifest = verify(v2_package)
    assert manifest['version'] == 2
    assert manifest['summary']['boundary_matches'] == 47
    assert manifest['summary']['segment_count'] == 514
    assert manifest['summary']['card_signal_count'] == 528
    assert manifest['summary']['card_week_count'] == 22
    assert {path.relative_to(v2_package).as_posix() for path in v2_package.rglob('*') if path.is_file()} == {
        *FILES_V2, 'manifest.json'
    }
    restored = restore(encode(v2_package))
    assert verify(restored) == manifest
    assert not (restored / 'local/private-row-level.csv').exists()

    settings = settings_from_package(v2_package).model_copy(update={'runtime_storage_root': tmp_path / 'runtime'})
    with TestClient(create_app(settings)) as client:
        readiness = client.get('/readiness').json()
        assert readiness['ready'] is True
        assert readiness['analysis']['workflow_version'] == 'regional-workflow-2'
        assert readiness['analysis']['boundary'] == {'matched': 47, 'total': 47}
        assert readiness['analysis']['card_coverage']['weeks'] == 22
        assert readiness['package']['identity_hash'] == manifest['package_id']
        assert str(v2_package) not in json.dumps(readiness)
        assert 'provenance' not in json.dumps(readiness)
        assert client.get('/analysis/groups?workflow_version=current').json()['metadata']['dataset_version'] == segments_v4.DATASET_VERSION


@pytest.mark.parametrize('mutation', ['tamper', 'extra', 'missing'])
def test_v2_package_rejects_changes(v2_package, mutation):
    path = v2_package / FILES_V2[0]
    if mutation == 'tamper':
        path.write_bytes(b'changed')
    elif mutation == 'extra':
        (v2_package / 'local/private-row-level.csv').write_text('not allowed')
    else:
        path.unlink()
    with pytest.raises(ValueError):
        verify(v2_package)


def test_v2_requires_verified_v1_catalog_and_confirmed_permission(tmp_path):
    v4 = v2_source(tmp_path / 'v4-source')
    with pytest.raises(ValueError, match='verified v1 catalog'):
        build(v4, tmp_path / 'missing-catalog', PROVENANCE, package_version=2)
    catalog = tmp_path/'catalog-v1'
    build(create_source(tmp_path/'catalog-source'), catalog,
          {**PROVENANCE, 'permission_status': 'private_contest_use_confirmed'})
    with pytest.raises(ValueError, match='outside catalog package'):
        build(v4, catalog/'nested-release', PROVENANCE, package_version=2, catalog_from_package=catalog)
    pending = tmp_path / 'pending-v1'
    build(create_source(tmp_path/'pending-source'), pending, PROVENANCE)
    package = tmp_path / 'pending-v2'
    build(v4, package, {**PROVENANCE, 'permission_status': 'private_contest_use_confirmed'},
          package_version=2, catalog_from_package=pending)
    assert verify(package)['provenance']['permission_status'] == 'pending'
    with pytest.raises(ValueError, match='confirmation required'):
        encode(package)
    with pytest.raises(ValueError, match='confirmation required'):
        settings_from_package(package)
    from backend.app.readiness import inspect
    readiness = inspect(Settings(_env_file=None, data_mode='local', input_root=package,
                                 regional_workflow_version='regional-workflow-2'))
    assert not readiness['ready'] and readiness['package']['status'] == 'unavailable'


def test_v2_readiness_does_not_fall_back_to_a_valid_v1_package(catalog_package):
    from backend.app.readiness import inspect
    readiness = inspect(Settings(_env_file=None, data_mode='local', input_root=catalog_package,
                                 regional_workflow_version='regional-workflow-2'))
    assert not readiness['ready']
    assert readiness['analysis']['reason'] == 'runtime_v2_inputs_missing_or_invalid'


def test_v2_build_keeps_export_source_unchanged(catalog_package, tmp_path):
    source = v2_source(tmp_path / 'v4-source')
    before = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in source.rglob('*') if path.is_file()}
    build(source, tmp_path/'release', {**PROVENANCE, 'permission_status': 'private_contest_use_confirmed'},
          package_version=2, catalog_from_package=catalog_package)
    after = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in source.rglob('*') if path.is_file()}
    assert after == before


def test_v2_rejects_catalog_changed_after_reference_verification(catalog_package, tmp_path, monkeypatch):
    from scripts import runtime_package
    source = v2_source(tmp_path/'v4-source')
    original_verify = runtime_package.verify

    def verify_then_change(root):
        manifest = original_verify(root)
        if Path(root) == catalog_package:
            path = catalog_package/'local/resources-v3.csv'
            path.write_bytes(path.read_bytes()+b'\n')
        return manifest

    monkeypatch.setattr(runtime_package, 'verify', verify_then_change)
    with pytest.raises(ValueError, match='catalog changed during build'):
        runtime_package.build(source, tmp_path/'release',
                              {**PROVENANCE, 'permission_status': 'private_contest_use_confirmed'},
                              package_version=2, catalog_from_package=catalog_package)
    assert not (tmp_path/'release').exists()


@pytest.mark.parametrize('field,value', [('version', True), ('workflow_version', 'regional-workflow-1'),
                                         ('package_id', '0' * 64)])
def test_v2_manifest_rejects_wrong_expected_identity(v2_package, field, value):
    manifest_path = v2_package / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(v2_package)


def test_v2_enforces_expanded_package_size(v2_package, monkeypatch):
    from scripts import runtime_package
    monkeypatch.setattr(runtime_package, 'MAX_INPUT_BYTES', 1)
    with pytest.raises(ValueError, match='expanded size'):
        verify(v2_package)
    with pytest.raises(ValueError, match='expanded size'):
        encode(v2_package)


@pytest.mark.parametrize('mutation', ['extra', 'traversal', 'duplicate', 'pending'])
def test_v2_restore_rejects_invalid_archive(v2_package, mutation):
    from scripts.runtime_package import restore

    entries = {path.relative_to(v2_package).as_posix(): path.read_bytes()
               for path in v2_package.rglob('*') if path.is_file()}
    if mutation == 'extra':
        entries['secret.csv'] = b'not allowed'
    elif mutation == 'traversal':
        entries['../escape.csv'] = entries.pop(FILES_V2[0])
    elif mutation == 'pending':
        manifest = json.loads(entries['manifest.json'])
        manifest['provenance']['permission_status'] = 'pending'
        entries['manifest.json'] = json.dumps(manifest).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
        if mutation == 'duplicate':
            with pytest.warns(UserWarning, match='Duplicate name'):
                archive.writestr(FILES_V2[0], entries[FILES_V2[0]])
    value = base64.b64encode(stream.getvalue()).decode()
    with pytest.raises(ValueError, match='invalid RUNTIME_INPUT_PACKAGE') as error:
        restore(value)
    assert value not in str(error.value)
