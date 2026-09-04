from __future__ import annotations

import base64
import binascii
import json
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from git_progressor.exceptions import StageGenerationError, StageValidationError
from git_progressor.intake.manifest import build_stage_manifest
from git_progressor.models import FileOperation, FileOperationType, ProjectPlan, StageManifest
from git_progressor.planner.schema import plan_sha256
from git_progressor.stages.filesystem import assert_no_ignored_files, inspect_tree


class StageGenerator:
    """Materialize complete stage snapshots from declarative file operations."""

    def __init__(self, project_dir: Path, project_id: UUID):
        self.project_dir = project_dir.resolve()
        self.project_id = project_id
        self.source_dir = self.project_dir / "source"
        self.stages_dir = self.project_dir / "stages"

    def generate(self, plan: ProjectPlan) -> tuple[StageManifest, ...]:
        self.stages_dir.mkdir(parents=True, exist_ok=True)
        plan_hash = plan_sha256(plan)
        manifests: list[StageManifest] = []
        previous: Path | None = None
        for stage in plan.stages:
            destination = self.stages_dir / f"{stage.number:03d}"
            manifest_path = self.stages_dir / f"{stage.number:03d}.manifest.json"
            if destination.exists() or manifest_path.exists():
                manifest = self._verify_existing(
                    destination, manifest_path, stage.number, plan_hash
                )
                manifests.append(manifest)
                previous = destination
                continue

            temporary = self.stages_dir / f".tmp-{stage.number:03d}-{uuid4()}"
            try:
                if previous is None:
                    temporary.mkdir()
                else:
                    shutil.copytree(previous, temporary, copy_function=shutil.copyfile)
                self._apply_operations(temporary, stage.operations)
                files = inspect_tree(temporary)
                assert_no_ignored_files(temporary, files)
                manifest = build_stage_manifest(
                    temporary, files, self.project_id, stage.number, plan_hash
                )
                temporary.replace(destination)
                self._write_manifest_atomic(manifest_path, manifest)
            except (
                OSError,
                ValueError,
                binascii.Error,
                StageGenerationError,
                StageValidationError,
            ) as exc:
                shutil.rmtree(temporary, ignore_errors=True)
                raise StageGenerationError(
                    f"stage {stage.number:03d} generation failed: {exc}"
                ) from exc
            manifests.append(manifest)
            previous = destination
        return tuple(manifests)

    def _apply_operations(self, root: Path, operations: tuple[FileOperation, ...]) -> None:
        for operation in operations:
            destination = root / Path(operation.path)
            exists = destination.is_file()
            if destination.exists() and not exists:
                raise StageGenerationError(f"operation target is not a file: {operation.path}")
            if operation.operation == FileOperationType.ADD and exists:
                raise StageGenerationError(f"add target already exists: {operation.path}")
            requires_existing = operation.operation in {
                FileOperationType.MODIFY,
                FileOperationType.DELETE,
            }
            if requires_existing and not exists:
                raise StageGenerationError(f"operation target does not exist: {operation.path}")
            if operation.operation == FileOperationType.DELETE:
                destination.unlink()
                self._remove_empty_parents(destination.parent, root)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if operation.source_path is not None:
                source = self.source_dir / Path(operation.source_path)
                if not source.is_file() or source.is_symlink():
                    raise StageGenerationError(
                        f"immutable source file does not exist: {operation.source_path}"
                    )
                shutil.copyfile(source, destination)
            else:
                try:
                    content = base64.b64decode(
                        operation.content_base64 or "", validate=True
                    )
                    destination.write_bytes(content)
                except binascii.Error as exc:
                    raise StageGenerationError(
                        f"invalid base64 content for {operation.path}"
                    ) from exc

    @staticmethod
    def _remove_empty_parents(directory: Path, root: Path) -> None:
        while directory != root and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent

    def _verify_existing(
        self, destination: Path, manifest_path: Path, stage_number: int, plan_hash: str
    ) -> StageManifest:
        if not destination.is_dir() or not manifest_path.is_file():
            raise StageGenerationError(f"stage {stage_number:03d} is only partially present")
        stored = StageManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        actual = build_stage_manifest(
            destination,
            inspect_tree(destination),
            self.project_id,
            stage_number,
            plan_hash,
        )
        if stored != actual:
            raise StageGenerationError(
                f"stage {stage_number:03d} already exists but does not match its manifest"
            )
        return actual

    @staticmethod
    def _write_manifest_atomic(path: Path, manifest: StageManifest) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
        temporary.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
