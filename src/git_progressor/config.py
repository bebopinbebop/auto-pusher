from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GIT_PROGRESSOR_", env_file=".env", extra="ignore"
    )

    data_dir: Path = Path("data")
    database_url: str = "sqlite:///./data/git-progressor.db"
    log_level: str = "INFO"
    max_file_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    analyzer_max_files: int = Field(default=5_000, gt=0)
    analyzer_max_metadata_file_size: int = Field(default=256 * 1024, gt=0)
    analyzer_max_analysis_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    analyzer_max_important_files: int = Field(default=25, gt=0)

    @field_validator("data_dir", mode="after")
    @classmethod
    def normalize_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("database_url")
    @classmethod
    def sqlite_only_for_mvp(cls, value: str) -> str:
        if not value.startswith("sqlite:///"):
            raise ValueError("the MVP supports only sqlite:/// database URLs")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
