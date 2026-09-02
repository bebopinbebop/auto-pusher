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
        paths = scan_project(source, self.max_file_bytes)
        self.scanner.assert_safe(source, paths)
        project_id = project_id or uuid4()
        manifest = build_manifest(source, paths, project_id)
        project_dir = self.data_dir / "projects" / str(project_id)
        if project_dir.exists():
            raise IntakeError(f"project already exists: {project_id}")
        source_dir = project_dir / "source"
        try:
            for name in ("source", "planning", "stages", "state"):
                (project_dir / name).mkdir(parents=True, exist_ok=False)
            for original, entry in zip(paths, manifest.files, strict=True):
                destination = source_dir / Path(entry.path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                if file_sha256(destination) != entry.sha256:
                    raise IntakeError(f"copy verification failed: {entry.path}")
                try:
                    os.chmod(destination, 0o444)
                except OSError:
                    pass
            (project_dir / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
            )
        except Exception:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise
        return manifest
