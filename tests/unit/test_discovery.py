import os
import shutil
from pathlib import Path

import pytest

from git_progressor.intake.discovery import ProjectDiscovery
from git_progressor.intake.multi import IngestResultType, MultiProjectIngestor
from git_progressor.intake.service import ProjectImporter
from git_progressor.storage.database import SQLiteDatabase
from git_progressor.storage.repositories import ProjectRepository


def write_python_project(path: Path, name: str = "sample") -> None:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (path / "app.py").write_text("print('ok')\n", encoding="utf-8")


def ingestor(tmp_path: Path) -> tuple[MultiProjectIngestor, SQLiteDatabase]:
    database = SQLiteDatabase(f"sqlite:///{tmp_path / 'state.db'}")
    database.migrate()
    service = MultiProjectIngestor(
        ProjectImporter(tmp_path / "data", 1024 * 1024), ProjectRepository(database)
    )
    return service, database


def test_discovers_sibling_projects_and_ignores_plain_directories(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    write_python_project(root / "alpha", "alpha")
    (root / "beta").mkdir()
    (root / "beta/package.json").write_text('{"name":"beta"}', encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes/todo.txt").write_text("later", encoding="utf-8")
    candidates = ProjectDiscovery().discover(root)
    assert [item.path.name for item in candidates] == ["alpha", "beta"]


def test_parent_boundary_wins_and_excluded_directories_are_not_projects(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    parent = root / "platform"
    parent.mkdir(parents=True)
    (parent / "package.json").write_text('{"name":"platform"}', encoding="utf-8")
    (parent / "examples/demo").mkdir(parents=True)
    (parent / "examples/demo/package.json").write_text('{"name":"demo"}', encoding="utf-8")
    dependency = root / "node_modules/dependency"
    dependency.mkdir(parents=True)
    (dependency / "package.json").write_text('{"name":"dependency"}', encoding="utf-8")
    candidates = ProjectDiscovery().discover(root)
    assert [item.path.name for item in candidates] == ["platform"]


def test_repeat_move_and_changed_content_preserve_logical_identity(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    original = root / "first-name"
    write_python_project(original, "stable-package")
    service, database = ingestor(tmp_path)

    first = service.ingest(root).results[0]
    second = service.ingest(root).results[0]
    moved = root / "moved-name"
    shutil.move(str(original), str(moved))
    third = service.ingest(root).results[0]
    (moved / "app.py").write_text("print('changed')\n", encoding="utf-8")
    fourth = service.ingest(root).results[0]

    assert first.result == IngestResultType.NEW
    assert second.result == IngestResultType.KNOWN
    assert third.result == IngestResultType.KNOWN
    assert fourth.result == IngestResultType.UPDATED
    assert {first.project_id, second.project_id, third.project_id, fourth.project_id} == {
        first.project_id
    }
    assert first.source_hash != fourth.source_hash
    with database.connect() as connection:
        revision_count = connection.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0]
    assert revision_count == 2


def test_unrelated_same_basename_projects_remain_distinct(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    write_python_project(root / "group-a/tool", "python-tool")
    node = root / "group-b/tool"
    node.mkdir(parents=True)
    (node / "package.json").write_text('{"name":"node-tool"}', encoding="utf-8")
    service, database = ingestor(tmp_path)
    report = service.ingest(root)
    assert report.imported_count == 2
    assert len({result.project_id for result in report.results}) == 2
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 2


def test_duplicate_copy_is_recognized_as_known(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    original = root / "original"
    duplicate = root / "copy"
    write_python_project(original, "copied-project")
    shutil.copytree(original, duplicate)
    service, database = ingestor(tmp_path)
    report = service.ingest(root)
    assert {result.result for result in report.results} == {
        IngestResultType.NEW,
        IngestResultType.KNOWN,
    }
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_structural_identity_accepts_changes_at_known_location(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "legacy-tool"
    project.mkdir(parents=True)
    (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (project / "app.py").write_text("print('one')\n", encoding="utf-8")
    service, _ = ingestor(tmp_path)
    first = service.ingest(root).results[0]
    (project / "app.py").write_text("print('two')\n", encoding="utf-8")
    second = service.ingest(root).results[0]
    assert first.result == IngestResultType.NEW
    assert second.result == IngestResultType.UPDATED
    assert first.project_id == second.project_id


def test_ambiguous_structural_identity_collision_fails_visibly(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    for group, content in (("group-a", "one"), ("group-b", "two")):
        project = root / group / "same-name"
        project.mkdir(parents=True)
        (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (project / "app.py").write_text(content, encoding="utf-8")
    service, database = ingestor(tmp_path)
    report = service.ingest(root)
    assert report.imported_count == 1
    assert report.failed_count == 1
    assert "structural identity matched" in next(
        result.error or "" for result in report.results if result.result == IngestResultType.FAILED
    )
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_failed_candidate_does_not_block_successful_import(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    write_python_project(root / "good", "good")
    write_python_project(root / "bad", "bad")
    (root / "bad/private.pem").write_text("credential-shaped file", encoding="utf-8")
    service, database = ingestor(tmp_path)
    report = service.ingest(root)
    assert report.imported_count == 1
    assert report.failed_count == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_candidate_symlink_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    outside = tmp_path / "outside"
    root.mkdir()
    write_python_project(outside, "outside")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted")
    assert ProjectDiscovery().discover(root) == ()
