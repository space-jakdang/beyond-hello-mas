"""Build a private v4 input from the supplied 2026-10-25 aggregate tables."""
import argparse
import csv
import hashlib
import json
import tempfile
import unicodedata
from pathlib import Path

from backend.app.config import ROOT
from backend.tools.card_alarm_v4 import parse as parse_card_alarms
from backend.tools.indicators import digest
from backend.tools.neighborhoods import boundaries
from backend.tools.segments_v4 import (
    DATASET_VERSION,
    FRAME_BY_AGE,
    SOURCE_AGE_BANDS,
    STAGE_LABEL,
    SegmentV4,
    validate,
    write_segments,
)

GENERATOR_VERSION = "1"
SOURCE_FILES = {
    "1_탐지/dong_stage_age.csv": "stage",
    "1_탐지/structural_risk_seoul.csv": "structure",
    "1_탐지/card_alarm_weekly.csv": "card",
}
REGION_NAME = {"강남": "강남구", "춘천": "춘천시"}
SEX = {"남": "M", "여": "F"}
STRUCTURAL_AGES = {"40대", "50대", "60대", "70대+"}
SOURCE_NAME_ALIASES = {("강남구", "일원2동"): "개포3동"}


def normalized(value):
    return unicodedata.normalize("NFC", value or "").strip()


def source_files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source must be a regular directory")
    root = root.resolve()
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("source contains a symlink")
        if path.is_file():
            name = normalized(path.relative_to(root).as_posix())
            if name in files:
                raise ValueError("duplicate normalized source path")
            files[name] = path
    missing = set(SOURCE_FILES) - set(files)
    if missing:
        raise ValueError("required v4 source tables are missing")
    return root, {name: files[name] for name in SOURCE_FILES}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path, required):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if (not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames))
                or not set(required) <= set(reader.fieldnames)):
            raise ValueError("source table columns do not match v4 contract")
        return list(reader)


def source_hashes(paths):
    return {name: sha256(path) for name, path in paths.items()}


def build_rows(stage_rows, structure_rows, features):
    locations = {}
    region_by_location = {}
    for feature in features:
        props = feature["properties"]
        region = props["region_name"]
        key = (region, normalized(props["dong_nm"]))
        if key in locations:
            raise ValueError("duplicate geographic boundary")
        locations[key] = props
        region_by_location[key] = next((name for name, value in REGION_NAME.items() if value == region), None)
    if set(region_by_location.values()) - set(REGION_NAME):
        raise ValueError("unsupported geographic boundary")

    structures = {}
    for row in structure_rows:
        district = normalized(row.get("자치구"))
        age = normalized(row.get("연령대"))
        if district != REGION_NAME["강남"] or age not in STRUCTURAL_AGES:
            continue
        name = normalized(row.get("행정동"))
        name = SOURCE_NAME_ALIASES.get((district, name), name)
        key = (name, SEX.get(normalized(row.get("성"))), age)
        if key in structures:
            raise ValueError("duplicate structural-risk source cell")
        value = normalized(row.get("서울대비"))
        structures[key] = float(value.removesuffix("배")) if value else None

    expected = set()
    for (region_name, dong_name), props in locations.items():
        region = region_by_location[(region_name, dong_name)]
        expected.update((props["sgg"], props["dong_cd"], sex, age)
                        for sex in SEX.values() for age in SOURCE_AGE_BANDS[region])
    expected_structure = {
        (normalized(props["dong_nm"]), sex, age)
        for (region_name, _), props in locations.items()
        if region_name == REGION_NAME["강남"]
        for sex in SEX.values() for age in STRUCTURAL_AGES
    }
    if not expected_structure <= structures.keys():
        raise ValueError("structural-risk cells do not cover the target geography")

    rows = []
    seen = set()
    unmatched = 0
    for raw in stage_rows:
        region = normalized(raw.get("지역"))
        if region not in REGION_NAME:
            continue
        age = normalized(raw.get("연령대"))
        sex = SEX.get(normalized(raw.get("성")))
        source_name = normalized(raw.get("행정동"))
        region_name = REGION_NAME[region]
        name = SOURCE_NAME_ALIASES.get((region_name, source_name), source_name)
        props = locations.get((region_name, name))
        if props is None or sex is None or age not in SOURCE_AGE_BANDS[region]:
            unmatched += 1
            continue
        district = normalized(raw.get("자치구"))
        if district and district != region_name:
            raise ValueError("source district does not match geography")
        key = (props["sgg"], props["dong_cd"], sex, age)
        if key in seen:
            raise ValueError("duplicate source stage cell")
        seen.add(key)
        stage = int(normalized(raw.get("단계")))
        label = normalized(raw.get("단계명"))
        if stage not in STAGE_LABEL or label != STAGE_LABEL[stage]:
            raise ValueError("source stage label does not match stage")
        frame = normalized(raw.get("틀"))
        if frame != FRAME_BY_AGE[age]:
            raise ValueError("source display frame does not match source age")
        structural = structures.get((name, sex, age)) if region == "강남" and age in STRUCTURAL_AGES else None
        rows.append(SegmentV4(
            source_region=region, sgg=props["sgg"], dong_cd=props["dong_cd"],
            dong_nm=props["dong_nm"], source_dong_name=source_name, sex=sex,
            source_age_band=age, frame=frame, source_bands={"dong_stage_age": [age]},
            source_stage=stage, source_stage_label=label,
            assessment_status="insufficient_evidence" if stage == -1 else
                              "small_population_hold" if stage == 0 else "assessed",
            base_stage=stage if stage > 0 else None,
            weakness_count=int(normalized(raw.get("약점수"))),
            reason=normalized(raw.get("이유")),
            population=float(normalized(raw.get("월평균인구"))),
            structural_risk_ratio=structural,
        ))
    if unmatched or seen != expected:
        raise ValueError("source stage cells do not match target geography")
    return validate(rows)


def export(source_root, destination):
    destination = Path(destination)
    resolved_destination = destination.resolve()
    private_roots = ((ROOT / "data/local").resolve(), Path("/private/releases").resolve())
    if not any(resolved_destination.is_relative_to(private_root) for private_root in private_roots):
        raise ValueError("destination must be under data/local or /private/releases")
    root, paths = source_files(source_root)
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination already exists")
    if resolved_destination.is_relative_to(root):
        raise ValueError("destination must be outside source")
    boundary_body, boundary_metadata = boundaries()
    geography_paths = {
        "data/geography/boundaries.geojson": ROOT / "data/geography/boundaries.geojson",
        "data/geography/manifest.json": ROOT / "data/geography/manifest.json",
    }
    checked_paths = {**paths, **geography_paths}
    before = source_hashes(checked_paths)
    if before["data/geography/boundaries.geojson"] != boundary_metadata["subset_sha256"]:
        raise ValueError("geographic boundary hash mismatch")
    stage_rows = read_csv(paths["1_탐지/dong_stage_age.csv"],
                          ("지역", "자치구", "행정동", "성", "연령대", "월평균인구", "틀", "단계", "단계명", "약점수", "이유"))
    structure_rows = read_csv(paths["1_탐지/structural_risk_seoul.csv"],
                              ("자치구", "행정동", "성", "연령대", "서울대비"))
    card_raw = paths["1_탐지/card_alarm_weekly.csv"].read_bytes()
    parse_card_alarms(card_raw)
    rows = build_rows(stage_rows, structure_rows, boundary_body["features"])
    after = source_hashes(checked_paths)
    if before != after:
        raise ValueError("source files changed during export")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
        output = Path(staging) / "release"
        local = output / "local"
        local.mkdir(parents=True)
        metadata = write_segments(local / "segments-v4.parquet", rows, "local", before)
        card_path = local / "seohee/card_alarm_weekly.csv"
        card_path.parent.mkdir(parents=True)
        card_path.write_bytes(card_raw)
        manifest = {
            "manifest_version": "1",
            "generator": f"scripts.export_seohee_v4:{GENERATOR_VERSION}",
            "input_schema_version": 4,
            "data_mode": "local",
            "geography_version": boundary_metadata["version"],
            "geography_hash": boundary_metadata["subset_sha256"],
            "dataset_version": DATASET_VERSION,
            "observation_year": 2025,
            "local_only": True,
            "source_hashes": before,
            "artifact_hashes": {
                "segments-v4.parquet": sha256(local / "segments-v4.parquet"),
                "seohee/card_alarm_weekly.csv": sha256(card_path),
            },
            "segment_input_hash": metadata["input_hash"],
            "input_hash": digest(before),
        }
        (local / "import.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        if source_hashes(checked_paths) != before:
            raise ValueError("source files changed during export")
        output.rename(destination)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    rows = export(args.source, args.destination)
    print(f"Built {len(rows)} private v4 aggregate cells.")
