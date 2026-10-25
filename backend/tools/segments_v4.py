"""Versioned group-stage input for Seohee's 2026-10-25 regional data."""
import json
from typing import Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.tools.indicators import digest

DATASET_VERSION = "seohee-region-20261025-1"
SOURCE_AGE_BANDS = {
    "강남": ("20대", "30대", "40대", "50대", "60대", "70대+"),
    "춘천": ("20대", "30대", "40대", "50대", "60대+"),
}
FRAME_BY_AGE = {
    "20대": "청년",
    "30대": "중년",
    "40대": "중년",
    "50대": "장년",
    "60대": "노년",
    "70대+": "노년",
    "60대+": "노년",
}
STAGE_LABEL = {-1: "판정 근거 부족", 0: "판정 보류", 1: "안정", 2: "관심", 3: "주의", 4: "경계", 5: "심각"}


class SegmentV4(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["4"] = "4"
    dataset_version: Literal["seohee-region-20261025-1"] = DATASET_VERSION
    observation_year: Literal[2025] = 2025
    source_region: Literal["강남", "춘천"]
    sgg: str = Field(pattern=r"^\d{5}$")
    dong_cd: str = Field(pattern=r"^\d{8}$")
    dong_nm: str = Field(min_length=1)
    source_dong_name: str = Field(min_length=1)
    sex: Literal["M", "F"]
    source_age_band: str
    frame: Literal["청년", "중년", "장년", "노년"]
    source_bands: dict[str, list[str]] = Field(min_length=1)
    source_stage: Literal[-1, 0, 1, 2, 3, 4, 5]
    source_stage_label: str = Field(min_length=1)
    assessment_status: Literal["assessed", "small_population_hold", "insufficient_evidence"]
    base_stage: int | None = Field(default=None, ge=1, le=5)
    weakness_count: int = Field(ge=0)
    reason: str = Field(min_length=1)
    population: float = Field(ge=0)
    structural_risk_ratio: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_source_contract(self):
        if not self.dong_cd.startswith(self.sgg):
            raise ValueError("dong code does not belong to district")
        if self.source_age_band not in SOURCE_AGE_BANDS[self.source_region]:
            raise ValueError("source age band does not belong to region")
        if self.frame != FRAME_BY_AGE[self.source_age_band]:
            raise ValueError("display frame does not match source age band")
        if self.source_bands != {"dong_stage_age": [self.source_age_band]}:
            raise ValueError("source bands must preserve the source cell")
        expected = (
            "insufficient_evidence" if self.source_stage == -1 else
            "small_population_hold" if self.source_stage == 0 else "assessed"
        )
        if self.assessment_status != expected:
            raise ValueError("assessment status does not match source stage")
        if self.source_stage >= 1:
            if self.base_stage != self.source_stage:
                raise ValueError("base stage must preserve the assessed source stage")
        elif self.base_stage is not None:
            raise ValueError("unassessed source stage cannot produce a base stage")
        if self.source_stage_label != STAGE_LABEL[self.source_stage]:
            raise ValueError("source stage label does not match source stage")
        if self.structural_risk_ratio is not None and (
            self.source_region != "강남" or self.source_age_band not in ("40대", "50대", "60대", "70대+")
        ):
            raise ValueError("structural risk is limited to Seoul ages 40 and over")
        return self


def validate(rows):
    if not rows:
        raise ValueError("empty v4 segments")
    keys = [(r.dataset_version, r.sgg, r.dong_cd, r.sex, r.source_age_band) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate v4 segment key")
    return rows


def write_segments(path, rows, data_mode, source_hashes):
    rows = validate(rows)
    if data_mode not in ("local", "sample"):
        raise ValueError("invalid v4 data mode")
    values = [r.model_dump(mode="json") for r in rows]
    metadata = {
        "schema_version": "4",
        "dataset_version": DATASET_VERSION,
        "data_mode": data_mode,
        "input_hash": digest(values),
        "source_hashes": source_hashes,
        "synthetic": data_mode == "sample",
    }
    table = pa.Table.from_pylist(values)
    table = table.replace_schema_metadata({b"beyond_hello": json.dumps(metadata, sort_keys=True).encode()})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pq.write_table(table, tmp)
    tmp.replace(path)
    return metadata


def load_segments(settings):
    path = settings.data_dir / "segments-v4.parquet"
    table = pq.read_table(path)
    metadata = json.loads(table.schema.metadata[b"beyond_hello"])
    if metadata["schema_version"] != "4" or metadata["dataset_version"] != DATASET_VERSION:
        raise ValueError("v4 schema/version mismatch")
    if metadata["data_mode"] != settings.data_mode:
        raise ValueError("v4 mode mismatch")
    values = table.to_pylist()
    for row in values:
        if isinstance(row.get("source_bands"), dict):
            row["source_bands"] = {k: v for k, v in row["source_bands"].items() if v is not None}
    rows = validate([SegmentV4.model_validate(row) for row in values])
    if digest([r.model_dump(mode="json") for r in rows]) != metadata["input_hash"]:
        raise ValueError("v4 checksum mismatch")
    return rows, metadata
