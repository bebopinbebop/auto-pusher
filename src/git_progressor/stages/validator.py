from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from git_progressor.exceptions import SecretDetectedError, StageValidationError
from git_progressor.intake.manifest import build_stage_manifest
from git_progressor.models import ManifestFile, ProjectManifest, ProjectPlan, StageManifest
from git_progressor.planner.schema import plan_sha256
from git_progressor.security import CredentialScanner
from git_progressor.stages.filesystem import assert_no_ignored_files, inspect_tree


@dataclass(frozen=True)
class TreeDifference:
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()

    @property
    def matches(self) -> bool:
        return not (self.missing or self.unexpected or self.modified)


@dataclass(frozen=True)
class StageValidationResult:
    stage_number: int
    valid: bool
    tree_hash: str | None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationReport:
    project_id: UUID
    project_name: str
    stages: tuple[StageValidationResult, ...]
    source_tree_hash: str | None
    final_tree_hash: str | None
    final_difference: TreeDifference
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return (
            not self.errors
            and all(stage.valid for stage in self.stages)
            and self.final_difference.matches
            and self.source_tree_hash == self.final_tree_hash
        )


class StageValidator:
    """Independently inspect snapshots, stored manifests, security, and final equality."""

    def __init__(
        self,
        project_dir: Path,
        project_manifest: ProjectManifest,
        scanner: CredentialScanner | None = None,
    ):
        self.project_dir = project_dir.resolve()
        self.project_manifest = project_manifest
        self.scanner = scanner or CredentialScanner()

    def validate(self, plan: ProjectPlan) -> ValidationReport:
        stages_dir = self.project_dir / "stages"
        plan_hash = plan_sha256(plan)
        errors = list(self._structural_errors(stages_dir, len(plan.stages)))
        results: list[StageValidationResult] = []
        actual_manifests: dict[int, StageManifest] = {}
        for stage in plan.stages:
            result, actual = self._validate_stage(stages_dir, stage.number, plan_hash)
            results.append(result)
            if actual is not None:
                actual_manifests[stage.number] = actual

        source_manifest: StageManifest | None = None
        try:
            source_files = inspect_tree(self.project_dir / "source")
            source_manifest = build_stage_manifest(
                self.project_dir / "source",
                source_files,
                self.project_manifest.project_id,
                len(plan.stages),
                plan_hash,
            )
            imported_difference = compare_files(
                self.project_manifest.files, source_manifest.files
            )
            if (
                not imported_difference.matches
                or self.project_manifest.source_hash != source_manifest.tree_hash
            ):
                errors.append("immutable source no longer matches its imported manifest")
        except StageValidationError as exc:
            errors.append(f"immutable source validation failed: {exc}")

        final_manifest = actual_manifests.get(len(plan.stages))
        difference = (
            compare_files(source_manifest.files, final_manifest.files)
            if source_manifest is not None and final_manifest is not None
            else TreeDifference()
        )
        return ValidationReport(
            project_id=self.project_manifest.project_id,
            project_name=self.project_manifest.name,
            stages=tuple(results),
            source_tree_hash=source_manifest.tree_hash if source_manifest else None,
            final_tree_hash=final_manifest.tree_hash if final_manifest else None,
            final_difference=difference,
            errors=tuple(errors),
        )

    def _validate_stage(
        self, stages_dir: Path, number: int, plan_hash: str
    ) -> tuple[StageValidationResult, StageManifest | None]:
        snapshot = stages_dir / f"{number:03d}"
        manifest_path = stages_dir / f"{number:03d}.manifest.json"
        errors: list[str] = []
        actual: StageManifest | None = None
        try:
            files = inspect_tree(snapshot)
            assert_no_ignored_files(snapshot, files)
            actual = build_stage_manifest(
                snapshot, files, self.project_manifest.project_id, number, plan_hash
            )
            self.scanner.assert_safe(snapshot, files)
            stored = StageManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            if stored != actual:
                errors.append("persisted manifest does not match snapshot contents")
        except (OSError, ValidationError, SecretDetectedError, StageValidationError) as exc:
            errors.append(str(exc))
        result = StageValidationResult(
            number, not errors, actual.tree_hash if actual else None, tuple(errors)
        )
        return result, actual

    @staticmethod
    def _structural_errors(stages_dir: Path, expected_count: int) -> tuple[str, ...]:
        if not stages_dir.is_dir():
            return ("stages directory does not exist",)
        expected_dirs = {f"{number:03d}" for number in range(1, expected_count + 1)}
        expected_manifests = {
            f"{number:03d}.manifest.json" for number in range(1, expected_count + 1)
        }
        actual_dirs = {path.name for path in stages_dir.iterdir() if path.is_dir()}
        actual_files = {path.name for path in stages_dir.iterdir() if path.is_file()}
        errors: list[str] = []
        for name in sorted(expected_dirs - actual_dirs):
            errors.append(f"missing stage directory: {name}")
        for name in sorted(actual_dirs - expected_dirs):
            errors.append(f"unexpected stage directory: {name}")
        for name in sorted(expected_manifests - actual_files):
            errors.append(f"missing stage manifest: {name}")
        for name in sorted(actual_files - expected_manifests):
            errors.append(f"unexpected stage metadata: {name}")
        return tuple(errors)


def compare_files(
    expected: tuple[ManifestFile, ...], actual: tuple[ManifestFile, ...]
) -> TreeDifference:
    expected_by_path = {item.path: item for item in expected}
    actual_by_path = {item.path: item for item in actual}
    expected_paths = set(expected_by_path)
    actual_paths = set(actual_by_path)
    modified = tuple(
        sorted(
            path
            for path in expected_paths & actual_paths
            if expected_by_path[path].sha256 != actual_by_path[path].sha256
            or expected_by_path[path].size != actual_by_path[path].size
        )
    )
    return TreeDifference(
        missing=tuple(sorted(expected_paths - actual_paths)),
        unexpected=tuple(sorted(actual_paths - expected_paths)),
        modified=modified,
    )


def load_project_manifest(project_dir: Path) -> ProjectManifest:
    return ProjectManifest.model_validate_json(
        (project_dir / "manifest.json").read_text(encoding="utf-8")
    )


def load_project_plan(project_dir: Path) -> ProjectPlan:
    return ProjectPlan.model_validate_json(
        (project_dir / "planning" / "plan.json").read_text(encoding="utf-8")
    )


def save_project_plan(project_dir: Path, plan: ProjectPlan) -> None:
    path = project_dir / "planning" / "plan.json"
    path.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
