from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    data_mode: Literal["sample", "local"] = "sample"
    llm_mode: Literal["fake", "live"] = "fake"
    openai_api_key: SecretStr | None = None

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
        return ROOT / "runtime" / self.data_mode
