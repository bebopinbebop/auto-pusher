from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from git_progressor.models import ManifestFile, ProjectManifest

LANGUAGE_SUFFIXES = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go",
    ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(files: list[ManifestFile]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda entry: entry.path):
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(item.sha256))
        digest.update(b"\0")
    return digest.hexdigest()


def build_manifest(root: Path, paths: list[Path], project_id: UUID) -> ProjectManifest:
    entries = tuple(
        ManifestFile(
            path=path.relative_to(root).as_posix(),
            sha256=file_sha256(path),
            size=path.stat().st_size,
        )
        for path in paths
    )
    languages = tuple(
        sorted(
            {
                LANGUAGE_SUFFIXES[path.suffix.lower()]
                for path in paths
                if path.suffix.lower() in LANGUAGE_SUFFIXES
            }
        )
    )
    return ProjectManifest(
        project_id=project_id,
        name=root.name,
        created_at=datetime.now(UTC),
        source_hash=tree_hash(list(entries)),
        languages=languages,
        files=entries,
    )
