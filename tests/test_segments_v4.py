import csv
import hashlib
import json
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.app.config import Settings
from backend.tools import card_alarm_v4, segments_v4
from scripts import export_seohee_v4

BANDS = segments_v4.SOURCE_AGE_BANDS["강남"]
SEX = {"M": "남", "F": "여"}


def fixture_source(root):
    source = root / "source"
    detections = source / "1_탐지"
    detections.mkdir(parents=True)
    feature = {
        "type": "Feature",
        "properties": {"region_name": "강남구", "sgg": "11230", "dong_cd": "11230001", "dong_nm": "개포3동"},
        "geometry": {"type": "Polygon", "coordinates": []},
    }
    stage_path = detections / "dong_stage_age.csv"
    fields = ["지역", "자치구", "행정동", "성", "연령대", "월평균인구", "틀", "단계", "단계명", "약점수", "이유"]
    stage_values = []
    for index, band in enumerate(BANDS):
        for sex in SEX.values():
            stage = (-1, 0, 1, 2, 3, 5)[index]
            stage_values.append({
                "지역": "강남", "자치구": "강남구", "행정동": "일원2동", "성": sex,
                "연령대": band, "월평균인구": "600", "틀": segments_v4.FRAME_BY_AGE[band],
                "단계": str(stage), "단계명": segments_v4.STAGE_LABEL[stage],
                "약점수": "0", "이유": "검증용 합성 이유",
            })
    with stage_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(stage_values)

    structure_path = detections / "structural_risk_seoul.csv"
    fields = ["자치구", "행정동", "성", "연령대", "서울대비"]
    structural = [
        {"자치구": "강남구", "행정동": "일원2동", "성": sex, "연령대": band, "서울대비": "1.50배"}
        for band in ("40대", "50대", "60대", "70대+")
        for sex in SEX.values()
    ]
    with structure_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(structural)
    card_path = detections / "card_alarm_weekly.csv"
    card_fields = ["지역", "성", "연령대", "주", "V배", "N배", "V단계", "N단계", "경보", "약기준", "강기준"]
    card_rows = [
        {"지역": region, "성": sex, "연령대": age, "주": "07/07", "V배": "", "N배": "",
         "V단계": "0.0", "N단계": "0.0", "경보": "0", "약기준": "0.95", "강기준": "0.90"}
        for region in ("강남", "춘천") for sex in SEX.values() for age in card_alarm_v4.CARD_AGE_BANDS
    ]
    with card_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=card_fields)
        writer.writeheader()
        writer.writerows(card_rows)

    geography = root / "data/geography"
    geography.mkdir(parents=True)
    boundary_bytes = b"synthetic boundary fixture"
    (geography / "boundaries.geojson").write_bytes(boundary_bytes)
    geography_metadata = {
        "version": "test-geography-1",
        "subset_sha256": hashlib.sha256(boundary_bytes).hexdigest(),
    }
    (geography / "manifest.json").write_text(json.dumps(geography_metadata))
    return source, [feature], stage_path, structure_path, card_path, geography_metadata


def test_v4_export_preserves_status_age_and_source_and_round_trips(tmp_path, monkeypatch):
    source, features, stage_path, structure_path, card_path, geography_metadata = fixture_source(tmp_path)
    before = (stage_path.read_bytes(), structure_path.read_bytes(), card_path.read_bytes())
    monkeypatch.setattr(export_seohee_v4, "ROOT", tmp_path)
    monkeypatch.setattr(export_seohee_v4, "boundaries", lambda: ({"features": features}, geography_metadata))
    destination = tmp_path / "data/local/release"

    rows = export_seohee_v4.export(source, destination)
    loaded, metadata = segments_v4.load_segments(Settings(data_mode="local", input_root=destination))
    cards, card_metadata = card_alarm_v4.load(Settings(data_mode="local", input_root=destination))
    manifest = json.loads((destination / "local/import.json").read_text())

    assert len(rows) == len(loaded) == 12
    assert all(row.dong_nm == "개포3동" and row.source_dong_name == "일원2동" for row in rows)
    assert [rows[index].source_age_band for index in range(0, 12, 2)] == list(BANDS)
    assert {row.source_stage: row.assessment_status for row in rows} == {
        -1: "insufficient_evidence", 0: "small_population_hold", 1: "assessed",
        2: "assessed", 3: "assessed", 5: "assessed",
    }
    assert all(row.base_stage is None for row in rows if row.source_stage <= 0)
    assert all(row.base_stage == row.source_stage for row in rows if row.source_stage > 0)
    assert all(row.structural_risk_ratio == 1.5 for row in rows if row.source_age_band in ("40대", "50대", "60대", "70대+"))
    assert (stage_path.read_bytes(), structure_path.read_bytes(), card_path.read_bytes()) == before
    assert len(cards) == 24 and all(row.baseline_status == "unavailable" for row in cards)
    assert card_metadata["sha256"] == manifest["artifact_hashes"]["seohee/card_alarm_weekly.csv"]
    assert metadata["dataset_version"] == segments_v4.DATASET_VERSION
    assert manifest["input_schema_version"] == 4
    assert manifest["generator"] == "scripts.export_seohee_v4:1"
    assert manifest["geography_version"] == "test-geography-1"
    assert not (destination / "local/1_탐지").exists()


def test_v4_export_rejects_missing_and_duplicate_cells_without_output(tmp_path, monkeypatch):
    source, features, stage_path, _, _, geography_metadata = fixture_source(tmp_path)
    monkeypatch.setattr(export_seohee_v4, "ROOT", tmp_path)
    monkeypatch.setattr(export_seohee_v4, "boundaries", lambda: ({"features": features}, geography_metadata))
    lines = stage_path.read_text(encoding="utf-8-sig").splitlines()
    stage_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8-sig")
    destination = tmp_path / "data/local/missing"
    with pytest.raises(ValueError, match="target geography"):
        export_seohee_v4.export(source, destination)
    assert not destination.exists()

    stage_path.write_text("\n".join(lines + [lines[1]]) + "\n", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="duplicate source stage"):
        export_seohee_v4.export(source, destination)
    assert not destination.exists()


def test_v4_reader_rejects_checksum_changes(tmp_path):
    row = segments_v4.SegmentV4(
        source_region="강남", sgg="11230", dong_cd="11230001", dong_nm="역삼1동",
        source_dong_name="역삼1동", sex="M", source_age_band="20대", frame="청년",
        source_bands={"dong_stage_age": ["20대"]}, source_stage=2, source_stage_label="관심",
        assessment_status="assessed", base_stage=2, weakness_count=1, reason="검증용",
        population=600,
    )
    path = tmp_path / "local/segments-v4.parquet"
    segments_v4.write_segments(path, [row], "local", {})
    manifest = {
        "input_schema_version": 4, "dataset_version": segments_v4.DATASET_VERSION,
        "data_mode": "local", "artifact_hashes": {"segments-v4.parquet": hashlib.sha256(path.read_bytes()).hexdigest()},
    }
    (tmp_path / "local/import.json").write_text(json.dumps(manifest))
    table = pq.read_table(path)
    changed = table.to_pylist()
    changed[0]["population"] = 601
    pq.write_table(pa.Table.from_pylist(changed).replace_schema_metadata(table.schema.metadata), path)
    manifest["artifact_hashes"]["segments-v4.parquet"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "local/import.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="checksum"):
        segments_v4.load_segments(Settings(data_mode="local", input_root=tmp_path))



def test_v4_export_detects_source_change_during_build(tmp_path, monkeypatch):
    source, features, stage_path, _, _, geography_metadata = fixture_source(tmp_path)
    monkeypatch.setattr(export_seohee_v4, "ROOT", tmp_path)
    monkeypatch.setattr(export_seohee_v4, "boundaries", lambda: ({"features": features}, geography_metadata))
    read_csv = export_seohee_v4.read_csv

    def mutate_after_read(path, required):
        rows = read_csv(path, required)
        if path.name == "dong_stage_age.csv":
            path.write_bytes(path.read_bytes() + b"\n")
        return rows

    monkeypatch.setattr(export_seohee_v4, "read_csv", mutate_after_read)
    destination = tmp_path / "data/local/changed"
    with pytest.raises(ValueError, match="changed during export"):
        export_seohee_v4.export(source, destination)
    assert not destination.exists()
    assert stage_path.exists()


def test_v4_export_rejects_public_destination(tmp_path, monkeypatch):
    source, _, _, _, _, _ = fixture_source(tmp_path)
    monkeypatch.setattr(export_seohee_v4, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="destination must be under"):
        export_seohee_v4.export(source, tmp_path / "data/releases/public")


def test_v4_export_detects_source_change_before_activation(tmp_path, monkeypatch):
    source, features, stage_path, _, _, geography_metadata = fixture_source(tmp_path)
    monkeypatch.setattr(export_seohee_v4, "ROOT", tmp_path)
    monkeypatch.setattr(export_seohee_v4, "boundaries", lambda: ({"features": features}, geography_metadata))
    write_segments = export_seohee_v4.write_segments

    def mutate_after_write(*args, **kwargs):
        result = write_segments(*args, **kwargs)
        stage_path.write_bytes(stage_path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(export_seohee_v4, "write_segments", mutate_after_write)
    destination = tmp_path / "data/local/changed-after-write"
    with pytest.raises(ValueError, match="changed during export"):
        export_seohee_v4.export(source, destination)
    assert not destination.exists()


def test_v4_csv_reader_rejects_duplicate_headers(tmp_path):
    path = tmp_path / "duplicate.csv"
    path.write_text("지역,지역\n강남,춘천\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns do not match"):
        export_seohee_v4.read_csv(path, ("지역",))
