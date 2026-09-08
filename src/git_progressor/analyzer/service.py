from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from git_progressor.analyzer.analyzer import ProjectAnalyzer
from git_progressor.analyzer.models import ProjectAnalysis
from git_progressor.exceptions import AnalysisError
from git_progressor.models import ProjectManifest
from git_progressor.storage.repositories import ProjectRepository


class AnalysisService:
    def __init__(
        self,
        data_dir: Path,
        repository: ProjectRepository,
        analyzer: ProjectAnalyzer,
    ) -> None:
        self.data_dir = data_dir
        self.repository = repository
        self.analyzer = analyzer

    def analyze(
        self, project_id: UUID, source_hash: str | None = None
    ) -> ProjectAnalysis:
        revision = self.repository.resolve_revision(project_id, source_hash)
        manifest = ProjectManifest.model_validate_json(
            Path(revision.manifest_path).read_text(encoding="utf-8")
        )
        if manifest.project_id != project_id or manifest.source_hash != revision.source_hash:
            raise AnalysisError("source revision manifest identity does not match stored state")
        analysis = self.analyzer.analyze(Path(revision.source_path), manifest)
        artifact_path = (
            self.data_dir
            / "projects"
            / str(project_id)
            / "analyses"
            / revision.source_hash
            / f"analyzer-v{analysis.analyzer_version}"
            / "project-analysis.json"
        )
        self._write_immutable(artifact_path, analysis)
        self.repository.record_analysis(
            project_id,
            revision.source_hash,
            analysis.analyzer_version,
            analysis.analysis_hash,
            artifact_path,
        )
        return analysis

    @staticmethod
    def _write_immutable(path: Path, analysis: ProjectAnalysis) -> None:
        serialized = json.dumps(analysis.model_dump(mode="json"), indent=2) + "\n"
        if path.exists():
            existing = ProjectAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
            if existing != analysis:
                raise AnalysisError(
                    "version-addressed analysis artifact differs from recomputation"
                )
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
        try:
            temporary.write_text(serialized, encoding="utf-8")
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
