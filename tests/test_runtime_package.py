import csv
import base64
import io
import json
from pathlib import Path
import shutil
import zipfile

import pytest
from backend.app.config import ROOT
from backend.tools.neighborhoods import boundaries
from backend.tools.segments_v3 import write_segments
from backend.tools.weekly_signals import synthetic
from scripts.generate_groups import generate
from scripts.runtime_package import build, verify, sha, FILES, encode, restore

PROVENANCE = {'purpose': 'synthetic contract test', 'sources': 'generated fixtures',
              'permission_status': 'pending', 'disposal': 'delete test directory'}


def create_source(root):
    geo, _ = boundaries()
    identity = next(f['properties'] for f in geo['features'] if f['properties']['sgg'] == '11230')
    row = generate()[0].model_copy(update={k: identity[k] for k in ('sgg', 'dong_cd', 'dong_nm')})
    write_segments(root/'local/segments-v3.parquet', [row], 'local')
    shutil.copyfile(ROOT/'data/sample/resources.csv', root/'local/resources-v3.csv')
    weekly = root/'local/seohee/provided/card_weekly_signals.csv'
    weekly.parent.mkdir(parents=True)
    rows = []
    for item in synthetic():
        row = {'시군구': {'11230': '서울 강남구', '32010': '강원 춘천시'}[item['sgg']],
               '성': {'M': '남성', 'F': '여성'}[item['sex']],
               '연령대': {'20s': '20대', '30s': '30대'}[item['age_band']], '주시작': item['week']}
        for ind, metric in item['metrics'].items():
            row.update({ind: metric['value'], ind+'_기준선8주': metric['baseline'],
                        ind+'_비율': metric['ratio'],
                        ind+'_경보': {'none': '없음', 'weak': '약', 'strong': '강'}[metric['signal']]})
        rows.append(row)
    with weekly.open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (root/'local/seohee/import.json').write_text(json.dumps({'files': {'provided/card_weekly_signals.csv': sha(weekly)}}))
    (root/'local/raw-mdis.csv').write_text('must never be shipped')
    (root/'local/events.sqlite3').write_text('must never be shipped')
    return root


@pytest.fixture
def source(tmp_path):
    return create_source(tmp_path/'source')


def test_package_only_required_inputs_and_rejects_overwrite(source, tmp_path):
    dest = tmp_path/'release'
    manifest = build(source, dest, PROVENANCE)
    assert verify(dest)['files'] == manifest['files']
    assert manifest['summary']['neighborhoods'] == 1
    assert {p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()} == {*FILES, 'manifest.json'}
    with pytest.raises(ValueError, match='new'):
        build(source, dest, PROVENANCE)
    assert verify(dest)['files'] == manifest['files']


@pytest.mark.parametrize('mutation', ['tamper', 'extra', 'symlink', 'missing'])
def test_package_rejects_mutated_release(source, tmp_path, mutation):
    dest = tmp_path/'release'
    build(source, dest, PROVENANCE)
    path = dest/FILES[0]
    if mutation == 'tamper':path.write_bytes(b'changed')
    if mutation == 'extra':(dest/'secret.csv').write_text('no')
    if mutation == 'symlink':
        path.unlink(); path.symlink_to(source/FILES[0])
    if mutation == 'missing':path.unlink()
    with pytest.raises(ValueError):verify(dest)


def test_invalid_source_never_creates_release(source, tmp_path):
    weekly = source/'local/seohee/provided/card_weekly_signals.csv'
    weekly.write_text('changed')
    with pytest.raises(ValueError, match='checksum'):
        build(source, tmp_path/'release', PROVENANCE)
    assert not (tmp_path/'release').exists()


@pytest.fixture
def confirmed_package(source, tmp_path):
    root = tmp_path/'release'
    build(source, root, {**PROVENANCE, 'permission_status': 'private_contest_use_confirmed'})
    return root


def test_deployment_entrypoint_restores_same_inputs_after_cold_start(confirmed_package, tmp_path, monkeypatch):
    import runpy
    from fastapi.testclient import TestClient
    from backend.tools.neighborhoods import group_analysis
    from backend.app.config import Settings
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_ENV', 'production')
    monkeypatch.setenv('RUNTIME_INPUT_PACKAGE', encode(confirmed_package))
    monkeypatch.setenv('DATA_MODE', 'sample')
    monkeypatch.setenv('RESOURCE_CATALOG', 'fixture')
    monkeypatch.setenv('LLM_MODE', 'fake')
    expected = group_analysis(Settings(_env_file=None, input_root=confirmed_package,
                                      data_mode='local', resource_catalog='v3', llm_mode='fake'))
    roots = []
    for instance in range(2):
        monkeypatch.setenv('RUNTIME_STORAGE_ROOT', str(tmp_path/f'state-{instance}'))
        app = runpy.run_path(str(ROOT/'app.py'))['app']
        settings = app.state.graph.settings
        roots.append(settings.input_root)
        with TestClient(app) as client:
            report = client.get('/readiness').json()
            assert report['ready'] and report['data_mode'] == 'local'
            assert report['catalog']['version'] == 'v3'
            assert report['analysis']['geometry'] == 'administrative_boundaries'
            actual = client.get('/analysis/groups?sex=all&age=all').json()
            current = client.get('/analysis/groups?workflow_version=current').json()
            assert actual['neighborhoods'] == expected['neighborhoods']
            assert actual['metadata']['input_hash'] == expected['metadata']['input_hash']
            assert current['metadata']['rule_version'] == 'seohee-region-2'
            assert client.get('/local/segments-v3.parquet').status_code == 404
    assert roots[0] != roots[1]
    assert verify(roots[0]) == verify(roots[1]) == verify(confirmed_package)


@pytest.mark.parametrize('mutation', ['tamper', 'extra', 'traversal', 'duplicate', 'pending'])
def test_deployment_package_rejects_invalid_archive(confirmed_package, mutation):
    entries = {p.relative_to(confirmed_package).as_posix(): p.read_bytes()
               for p in confirmed_package.rglob('*') if p.is_file()}
    if mutation == 'tamper':entries[FILES[0]] = b'changed'
    if mutation == 'extra':entries['secret.csv'] = b'not allowed'
    if mutation == 'traversal':entries['../escape.csv'] = entries.pop(FILES[0])
    if mutation == 'pending':
        manifest = json.loads(entries['manifest.json'])
        manifest['provenance']['permission_status'] = 'pending'
        entries['manifest.json'] = json.dumps(manifest).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():archive.writestr(name, value)
        if mutation == 'duplicate':
            with pytest.warns(UserWarning, match='Duplicate name'):
                archive.writestr(FILES[0], entries[FILES[0]])
    value = base64.b64encode(stream.getvalue()).decode()
    with pytest.raises(ValueError, match='invalid RUNTIME_INPUT_PACKAGE') as error:
        restore(value)
    assert value not in str(error.value)


def test_deployment_package_size_and_encoding_limits(confirmed_package, monkeypatch):
    from scripts import runtime_package
    value = encode(confirmed_package)
    for invalid in ('', 'not-base64!', base64.b64encode(b'not a zip').decode()):
        with pytest.raises(ValueError, match='RUNTIME_INPUT_PACKAGE'):restore(invalid)
    monkeypatch.setattr(runtime_package, 'MAX_INPUT_BYTES', 1)
    with pytest.raises(ValueError, match='expanded size'):encode(confirmed_package)
    with pytest.raises(ValueError, match='RUNTIME_INPUT_PACKAGE'):restore(value)
    monkeypatch.setattr(runtime_package, 'MAX_INPUT_BYTES', 8*1024*1024)
    monkeypatch.setattr(runtime_package, 'MAX_ENCODED_BYTES', 1)
    with pytest.raises(ValueError, match='environment budget'):encode(confirmed_package)
    with pytest.raises(ValueError, match='RUNTIME_INPUT_PACKAGE'):restore(value)


def test_pending_package_cannot_be_exported(source, tmp_path):
    root = tmp_path/'release'
    build(source, root, PROVENANCE)
    with pytest.raises(ValueError, match='confirmation required'):encode(root)


def test_encode_command_keeps_data_private_and_refuses_overwrite(confirmed_package, tmp_path, monkeypatch, capsys):
    from scripts.runtime_package import main
    output = tmp_path/'private.env-value'
    monkeypatch.setattr('sys.argv', ['runtime_package', 'encode', str(confirmed_package), '--output', str(output)])
    main()
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(capsys.readouterr().out) == {'encoded_bytes': len(output.read_text())}
    assert verify(restore(output.read_text())) == verify(confirmed_package)
    with pytest.raises(FileExistsError):main()


def test_unmatched_geometry_never_creates_release(source, tmp_path):
    row = generate()[0]
    write_segments(source/'local/segments-v3.parquet', [row], 'local')
    with pytest.raises(ValueError, match='geographic'):
        build(source, tmp_path/'release', PROVENANCE)
    assert not (tmp_path/'release').exists()


def test_symlink_source_and_nested_destination_rejected(source, tmp_path):
    with pytest.raises(ValueError, match='outside'):
        build(source, source/'release', PROVENANCE)
    path = source/FILES[0]
    copy = tmp_path/'copy.parquet'; shutil.copyfile(path, copy)
    path.unlink(); path.symlink_to(copy)
    with pytest.raises(ValueError, match='symlink'):
        build(source, tmp_path/'release', PROVENANCE)


@pytest.mark.parametrize('change', ['missing_provenance', 'unknown_permission', 'sample'])
def test_manifest_contract_rechecked(source, tmp_path, change):
    dest = tmp_path/'release'
    build(source, dest, PROVENANCE)
    path = dest/'manifest.json'; manifest = json.loads(path.read_text())
    if change == 'missing_provenance':manifest.pop('provenance')
    if change == 'unknown_permission':manifest['provenance']['permission_status'] = 'approved'
    if change == 'sample':manifest['data_mode'] = 'sample'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):verify(dest)


def test_symlink_destination_does_not_create_parent(source, tmp_path):
    outside = tmp_path/'outside'; outside.mkdir()
    link = tmp_path/'link'; link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        build(source, link/'new/release', PROVENANCE)
    assert not (outside/'new').exists()
