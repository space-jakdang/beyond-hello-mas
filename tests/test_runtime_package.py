import csv
import json
from pathlib import Path
import shutil

import pytest
from backend.app.config import ROOT
from backend.tools.neighborhoods import boundaries
from backend.tools.segments_v3 import write_segments
from backend.tools.weekly_signals import synthetic
from scripts.generate_groups import generate
from scripts.runtime_package import build, verify, sha, FILES

PROVENANCE = {'purpose': 'synthetic contract test', 'sources': 'generated fixtures',
              'permission_status': 'pending', 'disposal': 'delete test directory'}


@pytest.fixture
def source(tmp_path):
    root = tmp_path/'source'
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
