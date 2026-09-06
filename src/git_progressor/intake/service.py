from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from git_progressor.exceptions import IntakeError
from git_progressor.intake.manifest import build_manifest, file_sha256
from git_progressor.intake.scanner import scan_project
from git_progressor.models import ProjectManifest
from git_progressor.security import CredentialScanner


class ProjectImporter:
    def __init__(
        self,
        data_dir: Path,
        max_file_bytes: int,
        scanner: CredentialScanner | None = None,
    ):
        self.data_dir = data_dir
        self.max_file_bytes = max_file_bytes
        self.scanner = scanner or CredentialScanner()

    def ingest(self, source: Path, project_id: UUID | None = None) -> ProjectManifest:
        source = source.expanduser().resolve()
        project_id = project_id or uuid4()
        manifest, paths = self.inspect(source, project_id)
        project_dir = self.data_dir / "projects" / str(project_id)
        if project_dir.exists():
            raise IntakeError(f"project already exists: {project_id}")
        source_dir = project_dir / "source"
        try:
            for name in ("source", "planning", "stages", "state"):
                (project_dir / name).mkdir(parents=True, exist_ok=False)
            self._copy_files(source_dir, paths, manifest)
            (project_dir / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
            )
        except Exception:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise
        return manifest

    def inspect(
        self, source: Path, project_id: UUID
    ) -> tuple[ProjectManifest, list[Path]]:
        source = source.expanduser().resolve()
        paths = scan_project(source, self.max_file_bytes)
        self.scanner.assert_safe(source, paths)
        return build_manifest(source, paths, project_id), paths

    def ingest_revision(
        self, source: Path, project_id: UUID
    ) -> tuple[ProjectManifest, Path, Path, bool]:
        source = source.expanduser().resolve()
        manifest, paths = self.inspect(source, project_id)
        revisions_dir = self.data_dir / "projects" / str(project_id) / "revisions"
        destination = revisions_dir / manifest.source_hash
        source_dir = destination / "source"
        manifest_path = destination / "manifest.json"
        if destination.exists():
            return manifest, source_dir, manifest_path, False
        temporary = revisions_dir / f".tmp-{manifest.source_hash}-{uuid4()}"
        try:
            (temporary / "source").mkdir(parents=True)
            self._copy_files(temporary / "source", paths, manifest)
            (temporary / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
                encoding="utf-8",
            )
            revisions_dir.mkdir(parents=True, exist_ok=True)
            temporary.replace(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return manifest, source_dir, manifest_path, True

    @staticmethod
    def _copy_files(
        destination_root: Path, paths: list[Path], manifest: ProjectManifest
    ) -> None:
        for original, entry in zip(paths, manifest.files, strict=True):
            destination = destination_root / Path(entry.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
            if file_sha256(destination) != entry.sha256:
                raise IntakeError(f"copy verification failed: {entry.path}")
            try:
                os.chmod(destination, 0o444)
            except OSError:
                pass
