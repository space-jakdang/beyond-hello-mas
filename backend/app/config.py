from pathlib import Path
from uuid import UUID
from typing import Literal
import os

from pydantic import AliasChoices, Field, SecretStr, model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", allow_inf_nan=False)
    data_mode: Literal["sample", "local"] = "sample"
    input_root: Path | None = None
    runtime_storage_root: Path | None = None
    llm_mode: Literal["fake", "live"] = "fake"
    gov24_service_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GOV24_API_KEY", "GOV24_SERVICE_KEY")
    )
    policy_timeout_seconds: float = Field(default=10,gt=0,le=30)
    policy_max_pages: int = Field(default=30,ge=1,le=100)
    evaluation_id: UUID | None = None
    resource_catalog: Literal["fixture", "curated", "v3"] = "fixture"
    openai_api_key: SecretStr | None = None

    openai_model: str | None = None
    llm_budget_usd: float = Field(default=0, ge=0)
    llm_run_budget_usd: float | None = Field(default=None, gt=0)
    input_usd_per_million: float | None = Field(default=None, gt=0)
    output_usd_per_million: float | None = Field(default=None, gt=0)
    price_version: str | None = None
    llm_max_calls: int = Field(default=4, ge=1, le=10)
    llm_max_input_bytes: int = Field(default=24000, ge=1000, le=100000)
    llm_max_output_tokens: int = Field(default=1024, ge=128, le=8192)
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    person_mcp_mode: Literal["stub", "live"] = "stub"
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
        return (self.input_root or ROOT / "data") / self.data_mode

    @property
    def runtime_root(self) -> Path:
        if self.runtime_storage_root is not None:
            return self.runtime_storage_root
        # shortcut: per-instance temporary storage for Vercel previews; replace with shared persistence before multi-instance use.
        return Path("/tmp/beyond-hello-mas/runtime") if os.getenv("VERCEL") == "1" else ROOT / "runtime"

    @property
    def runtime_dir(self) -> Path:
        root = self.runtime_root / self.data_mode
        return root / "evaluations" / str(self.evaluation_id) if self.evaluation_id else root

    @property
    def catalog_path(self) -> Path:
        if self.resource_catalog == "v3":return self.data_dir / "resources-v3.csv"
        return ROOT / "data/catalog/curated-20261018-1/resources.csv" if self.resource_catalog == "curated" else self.data_dir / "resources.csv"
