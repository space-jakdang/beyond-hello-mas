from pathlib import Path
from uuid import UUID
from typing import Literal

from pydantic import Field, SecretStr, model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", allow_inf_nan=False)
    data_mode: Literal["sample", "local"] = "sample"
    llm_mode: Literal["fake", "live"] = "fake"
    gov24_service_key: SecretStr | None = None
    policy_timeout_seconds: float = Field(default=10,gt=0,le=30)
    policy_max_pages: int = Field(default=30,ge=1,le=100)
    evaluation_id: UUID | None = None
    resource_catalog: Literal["fixture", "curated"] = "fixture"
    openai_api_key: SecretStr | None = None

    openai_model: str | None = None
    llm_budget_usd: float = Field(default=0, ge=0)
    input_usd_per_million: float | None = Field(default=None, gt=0)
    output_usd_per_million: float | None = Field(default=None, gt=0)
    price_version: str | None = None
    llm_max_calls: int = Field(default=4, ge=1, le=10)
    llm_max_input_bytes: int = Field(default=24000, ge=1000, le=100000)
    llm_max_output_tokens: int = Field(default=1024, ge=128, le=8192)
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    mcp_python: str | None = None
    mcp_cwd: Path | None = None
    mcp_timeout_seconds: float = Field(default=10, gt=0, le=60)
    mcp_allow_fallback: bool = False

    @field_validator("evaluation_id", mode="before")
    @classmethod
    def blank_evaluation_id(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def live_requires_key(self):
        if self.llm_mode == "live" and not (
            self.openai_api_key and self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("live mode requires OPENAI_API_KEY")
        return self

    @property
    def data_dir(self) -> Path:
        return ROOT / "data" / self.data_mode

    @property
    def runtime_dir(self) -> Path:
        root = ROOT / "runtime" / self.data_mode
        return root / "evaluations" / str(self.evaluation_id) if self.evaluation_id else root

    @property
    def catalog_path(self) -> Path:
        return ROOT / "data/catalog/curated-20261018-1/resources.csv" if self.resource_catalog == "curated" else self.data_dir / "resources.csv"
