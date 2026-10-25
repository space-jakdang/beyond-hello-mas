"""Pinned regional workflow over the 2026-10-25 period aggregate and weekly cards."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.tools.indicators import digest
from backend.tools.segments_v4 import SOURCE_AGE_BANDS

VERSION = "regional-workflow-2"


class RegionalTaskV4(BaseModel):
    model_config = ConfigDict(extra="forbid")

    methodology_version: Literal["regional-workflow-2"] = VERSION
    sgg: Literal["11230", "32010"]
    as_of: date
    card_week: date
    sex: Literal["M", "F"]
    source_age_band: str
    dong_cd: str | None = Field(default=None, pattern=r"^\d{8}$")
    goal: str = Field(default="지역 신호와 통계를 검토하고 지원 자원을 제안하세요.", min_length=1, max_length=1000)

    @model_validator(mode="after")
    def scope(self):
        region = "강남" if self.sgg == "11230" else "춘천"
        if self.source_age_band not in SOURCE_AGE_BANDS[region]:
            raise ValueError("source age band does not belong to district")
        if self.dong_cd and not self.dong_cd.startswith(self.sgg):
            raise ValueError("dong outside task jurisdiction")
        if self.card_week.year != 2025 or self.card_week.weekday() != 0:
            raise ValueError("card week must be a 2025 Monday")
        if self.card_week > self.as_of:
            raise ValueError("card week is after analysis date")
        return self


def assess(settings, task, source_data=None):
    from backend.tools.neighborhoods import group_analysis_v4

    result = source_data if source_data is not None else group_analysis_v4(settings, task.card_week)
    segments = [row for row in result["segments"]
                if row["sgg"] == task.sgg and row["sex"] == task.sex
                and row["source_age_band"] == task.source_age_band
                and (task.dong_cd is None or row["dong_cd"] == task.dong_cd)]
    if not segments:
        raise ValueError("no observations for selected task")

    selected_bands = ("60대", "70대+") if task.sgg == "32010" and task.source_age_band == "60대+" else (task.source_age_band,)
    weekly = [row for row in result["weekly"]["signals"]
              if row["source_region"] == ("강남" if task.sgg == "11230" else "춘천")
              and row["sex"] == task.sex and row["source_age_band"] in selected_bands]
    task_data = {**task.model_dump(mode="json"), "age_group": task.source_age_band,
                 "ym": task.card_week.strftime("%Y-%m")}
    prepared = []
    for source in segments:
        row = {
            **source,
            "evidence_id": digest({"methodology_version": VERSION, "input_hash": result["metadata"]["input_hash"],
                                   "card_week": task.card_week.isoformat(), "source": source}),
            "age_group": source["source_age_band"],
            "index_name": "v4_stage_only",
            "value": None,
            "stage": source["final_stage"],
            "stage_label": source["final_stage_label"],
            "source_period": "2025 period aggregate",
            "source_file": "local/segments-v4.parquet",
            "flags": ["period_aggregate", "stage_only_no_continuous_index"],
            "residents": source["population"],
            "components": {},
            "ym": None,
            "methodology_version": VERSION,
        }
        prepared.append(row)

    dongs = {}
    for row in prepared:
        info = {key: row[key] for key in ("dong_cd", "dong_nm", "sgg")}
        item = dongs.setdefault(row["dong_cd"], {**info, "stage": None, "missing_age_bands": 1})
        item["stage"] = max(item["stage"] or 0, row["stage"] or 0) or None
        item["missing_age_bands"] = int(all(segment["stage"] is None for segment in prepared
                                             if segment["dong_cd"] == row["dong_cd"]))

    return {
        "segments": prepared,
        "dongs": list(dongs.values()),
        "task": task_data,
        "methodology_version": VERSION,
        "data_mode": settings.data_mode,
        "period_aggregate": True,
        "source_observations": prepared,
        "weekly_observations": weekly,
        "metadata": {
            **result["metadata"],
            "analysis_version": "v4",
            "workflow_version": VERSION,
            "methodology_version": VERSION,
            "review_contract_version": "statistics-review-2",
            "statistics_version": "3",
            "matching_mode": "deterministic-regional-1",
            "policy_gap_version": "policy-gap-1",
            "provisional": True,
            "card_signals_applied": True,
            "period_aggregate": True,
        },
    }
