from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from git_progressor.models import StrictModel


class AnalyzerLimits(StrictModel):
    max_files: int = Field(gt=0)
    max_metadata_file_size: int = Field(gt=0)
    max_analysis_bytes: int = Field(gt=0)
    max_important_files: int = Field(gt=0)


class Evidence(StrictModel):
    name: str
    paths: tuple[str, ...]


class Dependency(StrictModel):
    ecosystem: str
    name: str
    specification: str = ""
    source_path: str


class FileClassification(StrictModel):
    path: str
    kind: str
    size: int = Field(ge=0)


class ModuleComponent(StrictModel):
    path: str
    kind: str


class TestInventory(StrictModel):
    present: bool
    file_count: int = Field(ge=0)
    frameworks: tuple[str, ...]
    directories: tuple[str, ...]
    unit_files: int = Field(ge=0)
    integration_files: int = Field(ge=0)


class AnalysisStatistics(StrictModel):
    total_files: int = Field(ge=0)
    analyzed_files: int = Field(ge=0)
    skipped_files: int = Field(ge=0)
    total_source_bytes: int = Field(ge=0)
    metadata_bytes_read: int = Field(ge=0)
    important_files_selected: int = Field(ge=0)


class ProjectAnalysis(StrictModel):
    schema_version: int = 1
    analyzer_version: int = 1
    project_id: UUID
    source_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: AnalyzerLimits
    languages: tuple[Evidence, ...]
    frameworks_and_tools: tuple[Evidence, ...]
    dependencies: tuple[Dependency, ...]
    tests: TestInventory
    configuration: tuple[FileClassification, ...]
    infrastructure: tuple[FileClassification, ...]
    documentation: tuple[FileClassification, ...]
    entrypoints: tuple[Evidence, ...]
    modules: tuple[ModuleComponent, ...]
    important_files: tuple[str, ...]
    statistics: AnalysisStatistics
    warnings: tuple[str, ...]


class PlannerContext(StrictModel):
    schema_version: int = 1
    project_id: UUID
    source_revision: str
    analysis_hash: str
    languages: tuple[str, ...]
    frameworks_and_tools: tuple[str, ...]
    dependencies: tuple[Dependency, ...]
    tests: TestInventory
    configuration_paths: tuple[str, ...]
    infrastructure_paths: tuple[str, ...]
    documentation_paths: tuple[str, ...]
    entrypoints: tuple[Evidence, ...]
    modules: tuple[ModuleComponent, ...]
    important_files: tuple[str, ...]
    warnings: tuple[str, ...]


class AnalysisRecord(StrictModel):
    analysis_id: UUID
    project_id: UUID
    source_revision: str
    analyzer_version: int
    analysis_hash: str
    artifact_path: str
    created_at: datetime
