import hashlib
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend.app.config import Settings
from backend.app.contracts import SegmentV3
from backend.tools.segments_v3 import age_bands, validate, write_segments, load_segments
from scripts.generate_groups import generate
from scripts.import_seohee import import_bundle, inventory
from scripts.check_public import violations


def test_import_preserves_original_and_refuses_overwrite(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'1_점수표').mkdir()
    f=source/'1_점수표'/'fixture.csv';f.write_text('synthetic,value\nA,2\n')
    before=inventory(source);mtime=f.stat().st_mtime_ns;dest=tmp_path/'dest'
    assert import_bundle(source,dest)==before
    assert inventory(source)==before and f.stat().st_mtime_ns==mtime
    assert json.loads((dest/'import.json').read_text())['files']==before
    assert import_bundle(source,dest)==before
    f.write_text('changed')
    with pytest.raises(ValueError,match='differs'):import_bundle(source,dest)
    assert (dest/'1_점수표'/'fixture.csv').read_text()=='synthetic,value\nA,2\n'
    (source/'link').symlink_to(f)
    with pytest.raises(ValueError,match='symlink'):import_bundle(source,tmp_path/'other')


def test_manifest_guard_matches_renamed_content_and_denies_unknown_permissions():
    raw=b'private fixture';sha=hashlib.sha256(raw).hexdigest()
    for permission in ['MAS local only','pending','']:
        rules=[{'path':'original/source.csv','sha256':sha,'permission':permission}]
        assert violations('renamed.csv',raw,rules)
        assert violations('copy/original/source.csv',b'changed',rules)
    for permission in ['공개 가능','공개 가능 (출처 표기)']:
        assert not violations('renamed.csv',raw,[{'path':'original/source.csv','sha256':sha,'permission':permission}])


def test_v3_source_ages_and_contract():
    assert age_bands('sk_gangnam_s1','youth')==['20s','30s']
    assert age_bands('sk_chuncheon','youth')==['20s']
    assert age_bands('seoul_telecom','elderly')==['65+']
    row=generate()[0].model_dump()
    for changes in [{'sex':'X'},{'value':float('nan')},{'source_bands':{'sk':[]}},{'risk_direction':'high_is_risk'},{'dong_cd':'32010001'}]:
        with pytest.raises(ValidationError):SegmentV3.model_validate({**row,**changes})


def test_v3_sample_roundtrip_and_integrity(tmp_path,monkeypatch):
    rows=generate();assert len(rows)==2256
    assert rows==generate()
    with pytest.raises(ValueError):validate(rows+[rows[0]])
    with pytest.raises(ValueError):validate(rows[:-1],complete=True)
    import backend.app.config as config
    monkeypatch.setattr(config,'ROOT',tmp_path)
    settings=Settings(_env_file=None,llm_mode='fake')
    path=settings.data_dir/'segments-v3.parquet'
    write_segments(path,rows,'sample')
    loaded,meta=load_segments(settings);assert loaded==rows and meta['synthetic']
    import pyarrow.parquet as pq
    table=pq.read_table(path);data=table.to_pylist();data[0]['value']+=1
    import pyarrow as pa
    pq.write_table(pa.Table.from_pylist(data).replace_schema_metadata(table.schema.metadata),path)
    with pytest.raises(ValueError,match='checksum'):load_segments(settings)


def test_manifest_common_root_filename_does_not_block_unrelated_readme():
    rule={'path':'README.md','sha256':hashlib.sha256(b'private readme').hexdigest(),'permission':'private'}
    assert not violations('README.md',b'project docs',[rule])
    assert violations('README.md',b'private readme',[rule])
