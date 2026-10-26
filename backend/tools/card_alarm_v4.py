"""Version 4 region and age-band weekly card alarms."""
import csv
import hashlib
import io
import json
import re
from datetime import date
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.tools.segments_v4 import DATASET_VERSION

CARD_AGE_BANDS = ("20대", "30대", "40대", "50대", "60대", "70대+")
REGIONS = ("강남", "춘천")
SEX = {"남": "M", "여": "F"}
FIELDS = ("지역", "성", "연령대", "주", "V배", "N배", "V단계", "N단계", "경보", "약기준", "강기준")


class CardAlarmV4(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    dataset_version: Literal["seohee-region-20261025-1"] = DATASET_VERSION
    source_region: Literal["강남", "춘천"]
    sex: Literal["M", "F"]
    source_age_band: str
    week: date
    v_ratio: float | None = Field(default=None, ge=0)
    n_ratio: float | None = Field(default=None, ge=0)
    v_stage: Literal[0, 1, 2]
    n_stage: Literal[0, 1, 2]
    alarm_stage: Literal[0, 1, 2]
    baseline_status: Literal["unavailable", "observed"]
    weak_threshold: float = Field(gt=0, lt=1)
    strong_threshold: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def validate_card_contract(self):
        if self.source_age_band not in CARD_AGE_BANDS:
            raise ValueError("invalid card age band")
        if self.week.year != 2025 or self.week.weekday() != 0:
            raise ValueError("card week must be a 2025 Monday")
        if self.alarm_stage != min(self.v_stage, self.n_stage):
            raise ValueError("combined alarm must be the lower V/N stage")
        if self.strong_threshold >= self.weak_threshold:
            raise ValueError("strong threshold must be below weak threshold")
        missing = self.v_ratio is None and self.n_ratio is None
        if (self.v_ratio is None) != (self.n_ratio is None):
            raise ValueError("V and N ratios must be missing together")
        if missing:
            if self.baseline_status != "unavailable" or (self.v_stage, self.n_stage, self.alarm_stage) != (0, 0, 0):
                raise ValueError("missing baseline cannot have an alarm")
        elif self.baseline_status != "observed":
            raise ValueError("observed ratios need an available baseline")
        return self


def _number(value, optional=False):
    value = value.strip()
    if not value and optional:
        return None
    number = float(value)
    if not isfinite(number) or number < 0:
        raise ValueError("invalid card number")
    return number


def _stage(value):
    number = _number(value)
    if not number.is_integer() or int(number) not in (0, 1, 2):
        raise ValueError("invalid card stage")
    return int(number)


def _week(value):
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})", value.strip())
    if not match:
        raise ValueError("invalid card week")
    return date(2025, int(match.group(1)), int(match.group(2)))


def parse(raw):
    rows = []
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(FIELDS) <= set(reader.fieldnames):
        raise ValueError("card table columns do not match v4 contract")
    for row in reader:
        region = row["지역"].strip()
        sex = SEX.get(row["성"].strip())
        v_stage = _stage(row["V단계"])
        n_stage = _stage(row["N단계"])
        alarm = _stage(row["경보"])
        rows.append(CardAlarmV4(
            source_region=region, sex=sex, source_age_band=row["연령대"].strip(),
            week=_week(row["주"]), v_ratio=_number(row["V배"], optional=True),
            n_ratio=_number(row["N배"], optional=True), v_stage=v_stage, n_stage=n_stage,
            alarm_stage=alarm,
            baseline_status="unavailable" if not row["V배"].strip() else "observed",
            weak_threshold=_number(row["약기준"]), strong_threshold=_number(row["강기준"]),
        ))
    return validate(rows, complete=True)


def validate(rows, complete=False):
    if not rows:
        raise ValueError("empty v4 card signals")
    keys = [(r.source_region, r.sex, r.source_age_band, r.week) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate v4 card observation")
    groups = {(r.source_region, r.sex, r.source_age_band) for r in rows}
    weeks = {r.week for r in rows}
    if complete:
        expected = {(region, sex, age) for region in REGIONS for sex in ("M", "F") for age in CARD_AGE_BANDS}
        if groups != expected or any(
            {r.week for r in rows if (r.source_region, r.sex, r.source_age_band) == group} != weeks
            for group in expected
        ):
            raise ValueError("v4 card groups or weeks are incomplete")
    return rows


def load(settings):
    if settings.data_mode != "local":
        raise ValueError("v4 card signals require local data mode")
    root = settings.data_dir
    path = root / "seohee/card_alarm_weekly.csv"
    manifest_path = root / "import.json"
    if any(p.is_symlink() for p in (path, manifest_path, *path.parents, *manifest_path.parents)):
        raise ValueError("symlink v4 card input")
    raw = path.read_bytes()
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("input_schema_version") != 4
            or manifest.get("dataset_version") != DATASET_VERSION
            or manifest.get("data_mode") != settings.data_mode
            or hashlib.sha256(raw).hexdigest() != manifest.get("artifact_hashes", {}).get("seohee/card_alarm_weekly.csv")):
        raise ValueError("v4 card package version or checksum mismatch")
    return parse(raw), {"source": "card_alarm_weekly.csv", "sha256": hashlib.sha256(raw).hexdigest()}
