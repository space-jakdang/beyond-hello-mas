"""Versioned wire contracts. JSON Schema is exported by scripts/contracts.py."""
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import (AfterValidator, AwareDatetime, BaseModel, BeforeValidator,
                      ConfigDict, Field, HttpUrl, model_validator)

Code = Annotated[str, Field(pattern=r"^\d{8}$")]
District = Annotated[str, Field(pattern=r"^\d{5}$")]
Month = Annotated[str, Field(pattern=r"^2025-(0[7-9]|1[0-2])$")]
Nonempty = Annotated[str, Field(min_length=1)]
AgeBand = Literal["10s", "20s", "30s", "40s", "50s", "60plus"]


def seoul_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return value


SimTime = Annotated[AwareDatetime, BeforeValidator(seoul_time)]
WallTime = Annotated[AwareDatetime, AfterValidator(lambda dt: dt.astimezone(timezone.utc))]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["1"] = "1"


class Segment(Contract):
    schema_version: Literal["2"] = "2"
    ym: Month
    sgg: District
    dong_cd: Code
    dong_nm: Nonempty
    age_band: AgeBand
    x: float
    y: float
    crs: Nonempty
    coordinate_source: Nonempty
    indicators: dict[str, float | None]
    indicator_version: Nonempty
    residents: Annotated[int, Field(ge=0)] | None
    blind_flag: bool

    @model_validator(mode="after")
    def district_matches(self):
        if not self.dong_cd.startswith(self.sgg):
            raise ValueError("dong_cd must belong to sgg (statistical codes)")
        return self


class Scenario(Contract):
    id: Nonempty
    type: Literal["monthly", "case", "crisis", "question"]
    sim_time: SimTime
    payload: dict[str, Any]

    @model_validator(mode="after")
    def no_answers(self):
        def check(value):
            if isinstance(value, dict):
                if "expected" in value:
                    raise ValueError("expected belongs in evaluation labels, not runtime payload")
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        check(self.payload)
        return self


class EvaluationLabel(Contract):
    scenario_id: Nonempty
    label_version: Nonempty
    expected: dict[str, Any]


class Resource(Contract):
    id: Nonempty
    jurisdiction: list[Nonempty] = Field(min_length=1)
    name: Nonempty
    age_min: int = Field(ge=0, le=120)
    age_max: int = Field(ge=0, le=120)
    eligibility: Nonempty
    needs: list[Nonempty] = Field(min_length=1)
    intensity: Literal["low", "medium", "high"]
    delivery: Nonempty
    access: Literal["application", "outreach", "both"]
    isolation_relevance: Nonempty
    source_url: HttpUrl
    collected_at: WallTime
    evidence: Nonempty
    catalog_version: Nonempty

    @model_validator(mode="after")
    def age_range(self):
        if self.age_min > self.age_max:
            raise ValueError("age_min exceeds age_max")
        return self


class Run(Contract):
    id: Nonempty
    scenario_id: Nonempty
    thread_id: Nonempty
    status: Literal["pending", "running", "awaiting_approval", "completed", "rejected", "failed"]
    data_mode: Literal["sample", "local"]
    llm_mode: Literal["fake", "live"]
    input_version: Nonempty
    rule_version: Nonempty
    model_version: Nonempty
    prompt_version: Nonempty
    catalog_version: Nonempty
    started_at: WallTime
    ended_at: WallTime | None = None
    error: str | None = None


class Trace(Contract):
    run_id: Nonempty
    scenario_id: Nonempty
    seq: int = Field(ge=1)
    wall_ts: WallTime
    sim_ts: SimTime
    agent: Literal["supervisor", "classify", "match", "approval", "link", "curator", "system"]
    kind: Literal["node_start", "node_end", "tool_call", "tool_result", "llm_call", "llm_result", "route", "interrupt", "alert", "error", "approval", "received", "acknowledged", "run_end"]
    payload: dict[str, Any]
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)


class Approval(Contract):
    id: Nonempty
    run_id: Nonempty
    snapshot_version: Nonempty
    status: Literal["pending", "approved", "rejected"]
    operator: Nonempty | None = None
    reason: Nonempty | None = None
    decided_at: WallTime | None = None

    @model_validator(mode="after")
    def decision(self):
        if self.status == "pending":
            if any(v is not None for v in (self.operator, self.reason, self.decided_at)):
                raise ValueError("pending approval cannot contain a decision")
        elif self.operator is None or self.decided_at is None:
            raise ValueError("decision requires operator and time")
        if self.status == "rejected" and not self.reason:
            raise ValueError("rejection requires reason")
        return self


class Alert(Contract):
    id: Nonempty
    run_id: Nonempty
    approval_id: Nonempty | None = None
    type: Literal["crisis", "approval_requested", "linkage_completed"]
    status: Literal["created", "received", "acknowledged"]
    created_at: WallTime
    received_at: WallTime | None = None
    acknowledged_at: WallTime | None = None

    @model_validator(mode="after")
    def state(self):
        if self.type == "approval_requested" and not self.approval_id:
            raise ValueError("approval request requires approval_id")
        if self.status in ("received", "acknowledged") and self.received_at is None:
            raise ValueError("received timestamp required")
        if self.status == "acknowledged" and self.acknowledged_at is None:
            raise ValueError("acknowledgement timestamp required")
        if self.status == "created" and (self.received_at or self.acknowledged_at):
            raise ValueError("created alert cannot contain receipt or acknowledgement")
        if self.status == "received" and self.acknowledged_at:
            raise ValueError("received alert cannot contain acknowledgement")
        times = [t for t in (self.created_at, self.received_at, self.acknowledged_at) if t]
        if times != sorted(times):
            raise ValueError("alert timestamps must be ordered")
        return self
