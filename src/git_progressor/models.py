from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectStatus(StrEnum):
    IMPORTED = "IMPORTED"
    PLANNED = "PLANNED"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    PAUSED = "PAUSED"


class PublicationStatus(StrEnum):
    PLANNED = "PLANNED"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class ManifestFile(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ValueError("manifest paths must be safe relative POSIX paths")
        return value


class ProjectManifest(StrictModel):
    schema_version: int = 1
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    created_at: datetime
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    files: tuple[ManifestFile, ...]


class PlanStage(StrictModel):
    number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    files_added: tuple[str, ...] = ()
    files_modified: tuple[str, ...] = ()
    files_removed: tuple[str, ...] = ()
    reasoning: str = Field(min_length=1)
    suggested_commit_message: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def file_operations_are_disjoint(self) -> PlanStage:
        groups = [set(self.files_added), set(self.files_modified), set(self.files_removed)]
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("a file cannot have multiple operations in one stage")
        for item in set().union(*groups):
            ManifestFile(path=item, sha256="0" * 64, size=0)
        return self


class ProjectPlan(StrictModel):
    schema_version: int = 1
    project_summary: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    stages: tuple[PlanStage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_contiguous_stages(self) -> ProjectPlan:
        numbers = [stage.number for stage in self.stages]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("stage numbers must be ordered and contiguous from 1")
        return self

