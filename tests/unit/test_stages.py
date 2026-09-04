import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from git_progressor.exceptions import StageGenerationError
from git_progressor.intake.service import ProjectImporter
from git_progressor.models import FileOperation, FileOperationType, ProjectPlan
from git_progressor.stages.generator import StageGenerator
from git_progressor.stages.validator import StageValidator, compare_files

FIXTURES = Path(__file__).parents[1] / "fixtures"
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000123")


def prepared_project(tmp_path: Path):
    manifest = ProjectImporter(tmp_path / "data", 1024 * 1024).ingest(
        FIXTURES / "calculator-final", PROJECT_ID
    )
    project_dir = tmp_path / "data" / "projects" / str(PROJECT_ID)
    plan = ProjectPlan.model_validate_json(
        (FIXTURES / "calculator-plan.json").read_text(encoding="utf-8")
    )
    return project_dir, manifest, plan


def test_sequential_generation_add_modify_delete_and_final_equality(tmp_path: Path) -> None:
    project_dir, source_manifest, plan = prepared_project(tmp_path)
    manifests = StageGenerator(project_dir, PROJECT_ID).generate(plan)
    assert len(manifests) == 5
    assert (project_dir / "stages/001/calculator/core.py").is_file()
    assert (project_dir / "stages/002/scratch.txt").is_file()
    assert not (project_dir / "stages/003/scratch.txt").exists()
    assert (project_dir / "stages/004/tests/test_core.py").is_file()
    assert manifests[-1].tree_hash == source_manifest.source_hash
    assert not compare_files(source_manifest.files, manifests[-1].files).missing


def test_generation_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    project_dir, _, plan = prepared_project(tmp_path)
    generator = StageGenerator(project_dir, PROJECT_ID)
    first = generator.generate(plan)
    second = generator.generate(plan)
    assert first == second


def test_regeneration_refuses_tampered_snapshot(tmp_path: Path) -> None:
    project_dir, _, plan = prepared_project(tmp_path)
    generator = StageGenerator(project_dir, PROJECT_ID)
    generator.generate(plan)
    (project_dir / "stages/002/scratch.txt").write_bytes(b"changed")
    with pytest.raises(StageGenerationError, match="does not match its manifest"):
        generator.generate(plan)


def test_failed_stage_never_appears_as_complete(tmp_path: Path) -> None:
    project_dir, _, plan = prepared_project(tmp_path)
    failing_operation = FileOperation(
        operation=FileOperationType.DELETE, path="does-not-exist.txt"
    )
    broken = plan.model_copy(
        update={
            "stages": plan.stages[:1]
            + (plan.stages[1].model_copy(update={"operations": (failing_operation,)}),)
        }
    )
    with pytest.raises(StageGenerationError, match="does not exist"):
        StageGenerator(project_dir, PROJECT_ID).generate(broken)
    assert not (project_dir / "stages/002").exists()
    assert not (project_dir / "stages/002.manifest.json").exists()
    assert not list((project_dir / "stages").glob(".tmp-*"))


def test_validator_accepts_exact_final_state(tmp_path: Path) -> None:
    project_dir, manifest, plan = prepared_project(tmp_path)
    StageGenerator(project_dir, PROJECT_ID).generate(plan)
    report = StageValidator(project_dir, manifest).validate(plan)
    assert report.valid
    assert report.source_tree_hash == report.final_tree_hash
    assert report.final_difference.matches


@pytest.mark.parametrize(
    ("mutation", "category"),
    [
        ("missing", "missing"),
        ("unexpected", "unexpected"),
        ("modified", "modified"),
    ],
)
def test_validator_reports_final_tree_tampering(
    tmp_path: Path, mutation: str, category: str
) -> None:
    project_dir, manifest, plan = prepared_project(tmp_path)
    StageGenerator(project_dir, PROJECT_ID).generate(plan)
    final = project_dir / "stages/005"
    if mutation == "missing":
        (final / "README.md").unlink()
    elif mutation == "unexpected":
        (final / "debug.log").write_bytes(b"debug")
    else:
        (final / "calculator/core.py").write_bytes(b"changed")
    report = StageValidator(project_dir, manifest).validate(plan)
    assert not report.valid
    assert getattr(report.final_difference, category)


def test_validator_detects_intermediate_and_manifest_tampering(tmp_path: Path) -> None:
    project_dir, manifest, plan = prepared_project(tmp_path)
    StageGenerator(project_dir, PROJECT_ID).generate(plan)
    (project_dir / "stages/002/scratch.txt").write_bytes(b"changed")
    stored = json.loads((project_dir / "stages/003.manifest.json").read_text(encoding="utf-8"))
    stored["tree_hash"] = "0" * 64
    (project_dir / "stages/003.manifest.json").write_text(json.dumps(stored), encoding="utf-8")
    report = StageValidator(project_dir, manifest).validate(plan)
    assert not report.valid
    assert not report.stages[1].valid
    assert not report.stages[2].valid


def test_validator_runs_credential_scanner(tmp_path: Path) -> None:
    project_dir, manifest, plan = prepared_project(tmp_path)
    StageGenerator(project_dir, PROJECT_ID).generate(plan)
    (project_dir / "stages/003/leaked.pem").write_bytes(b"not a real key")
    report = StageValidator(project_dir, manifest).validate(plan)
    assert not report.valid
    assert "blocked-credential-file" in " ".join(report.stages[2].errors)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_validator_rejects_symlink(tmp_path: Path) -> None:
    project_dir, manifest, plan = prepared_project(tmp_path)
    StageGenerator(project_dir, PROJECT_ID).generate(plan)
    link = project_dir / "stages/003/link.py"
    try:
        link.symlink_to(project_dir / "stages/003/calculator/core.py")
    except OSError:
        pytest.skip("symlink creation is not permitted")
    report = StageValidator(project_dir, manifest).validate(plan)
    assert not report.valid
    assert "symbolic link" in " ".join(report.stages[2].errors)
