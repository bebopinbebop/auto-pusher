import json
from pathlib import Path
from uuid import UUID

import pytest

from git_progressor.exceptions import IntakeError, SecretDetectedError
from git_progressor.intake.manifest import build_manifest
from git_progressor.intake.scanner import scan_project
from git_progressor.intake.service import ProjectImporter


def test_scan_respects_gitignore_and_default_exclusions(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("no\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("no\n", encoding="utf-8")
    paths = scan_project(tmp_path, 1024)
    assert [path.name for path in paths] == [".gitignore", "keep.py"]


def test_manifest_hash_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "b.py"
    second = tmp_path / "a.py"
    first.write_bytes(b"b")
    second.write_bytes(b"a")
    project_id = UUID("00000000-0000-0000-0000-000000000001")
    one = build_manifest(tmp_path, [first, second], project_id)
    two = build_manifest(tmp_path, [second, first], project_id)
    assert one.source_hash == two.source_hash


def test_import_copies_and_verifies_source(tmp_path: Path) -> None:
    source = tmp_path / "source-project"
    source.mkdir()
    (source / "app.py").write_bytes(b"print('hello')\n")
    data = tmp_path / "data"
    manifest = ProjectImporter(data, 1024).ingest(source)
    project_dir = data / "projects" / str(manifest.project_id)
    assert (project_dir / "source" / "app.py").read_bytes() == b"print('hello')\n"
    persisted = json.loads((project_dir / "manifest.json").read_text(encoding="utf-8"))
    assert persisted["source_hash"] == manifest.source_hash


def test_import_rejects_secret_file(tmp_path: Path) -> None:
    (tmp_path / "service.pem").write_text("not-even-a-real-key", encoding="utf-8")
    with pytest.raises(SecretDetectedError, match="blocked-credential-file"):
        ProjectImporter(tmp_path / "data", 1024).ingest(tmp_path)


def test_scan_rejects_oversized_file(tmp_path: Path) -> None:
    (tmp_path / "large.bin").write_bytes(b"1234")
    with pytest.raises(IntakeError, match="size limit"):
        scan_project(tmp_path, 3)

