from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from git_progressor.exceptions import IdentityConflictError
from git_progressor.intake.discovery import ProjectCandidate, ProjectDiscovery
from git_progressor.intake.identity import SourceIdentityResolver
from git_progressor.intake.service import ProjectImporter
from git_progressor.models import IdentityConfidence
from git_progressor.storage.repositories import ProjectRepository


class IngestResultType(StrEnum):
    NEW = "NEW"
    UPDATED = "UPDATED"
    KNOWN = "KNOWN"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProjectIngestResult:
    candidate: ProjectCandidate
    result: IngestResultType
    project_id: UUID | None = None
    source_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class MultiIngestReport:
    root: Path
    results: tuple[ProjectIngestResult, ...]

    @property
    def imported_count(self) -> int:
        accepted = {IngestResultType.NEW, IngestResultType.UPDATED}
        return sum(item.result in accepted for item in self.results)

    @property
    def known_count(self) -> int:
        return sum(item.result == IngestResultType.KNOWN for item in self.results)

    @property
    def failed_count(self) -> int:
        return sum(item.result == IngestResultType.FAILED for item in self.results)


class MultiProjectIngestor:
    def __init__(
        self,
        importer: ProjectImporter,
        repository: ProjectRepository,
        discovery: ProjectDiscovery | None = None,
        identities: SourceIdentityResolver | None = None,
    ):
        self.importer = importer
        self.repository = repository
        self.discovery = discovery or ProjectDiscovery()
        self.identities = identities or SourceIdentityResolver()

    def ingest(self, root: Path) -> MultiIngestReport:
        root = root.expanduser().resolve()
        candidates = self.discovery.discover(root)
        results = tuple(self._ingest_candidate(candidate) for candidate in candidates)
        return MultiIngestReport(root, results)

    def _ingest_candidate(self, candidate: ProjectCandidate) -> ProjectIngestResult:
        try:
            identity = self.identities.resolve(candidate)
            existing = self.repository.find_by_source_identity(identity.value)
            if existing is None:
                return self._import_new(candidate, identity.value, identity.confidence)

            manifest, _ = self.importer.inspect(candidate.path, existing.project_id)
            revision = self.repository.find_revision(
                existing.project_id, manifest.source_hash
            )
            if revision is not None:
                self.repository.mark_seen(existing.project_id, candidate.path)
                return ProjectIngestResult(
                    candidate,
                    IngestResultType.KNOWN,
                    existing.project_id,
                    manifest.source_hash,
                )

            same_location = (
                existing.last_seen_path is not None
                and Path(existing.last_seen_path).resolve() == candidate.path.resolve()
            )
            if identity.confidence != IdentityConfidence.DECLARED and not same_location:
                raise IdentityConflictError(
                    "structural identity matched at a new path with different content"
                )
            manifest, source_path, manifest_path, _ = self.importer.ingest_revision(
                candidate.path, existing.project_id
            )
            self.repository.add_revision(
                existing.project_id,
                manifest.source_hash,
                manifest_path,
                source_path,
                candidate.path,
            )
            self.repository.mark_seen(existing.project_id, candidate.path)
            return ProjectIngestResult(
                candidate,
                IngestResultType.UPDATED,
                existing.project_id,
                manifest.source_hash,
            )
        except Exception as exc:
            return ProjectIngestResult(candidate, IngestResultType.FAILED, error=str(exc))

    def _import_new(
        self,
        candidate: ProjectCandidate,
        source_identity: str,
        confidence: IdentityConfidence,
    ) -> ProjectIngestResult:
        project_id = uuid4()
        manifest = self.importer.ingest(candidate.path, project_id)
        project_dir = self.importer.data_dir / "projects" / str(project_id)
        manifest_path = project_dir / "manifest.json"
        source_path = project_dir / "source"
        self.repository.add(
            manifest,
            str(manifest_path),
            source_identity,
            confidence.value,
            str(candidate.path),
        )
        self.repository.add_revision(
            project_id,
            manifest.source_hash,
            manifest_path,
            source_path,
            candidate.path,
        )
        return ProjectIngestResult(
            candidate,
            IngestResultType.NEW,
            project_id,
            manifest.source_hash,
        )

