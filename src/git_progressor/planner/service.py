from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from pydantic import ValidationError

from git_progressor.analyzer.analyzer import ProjectAnalyzer
from git_progressor.analyzer.context import PlannerContextBuilder
from git_progressor.analyzer.models import AnalyzerLimits
from git_progressor.exceptions import InvalidPlanError
from git_progressor.intake.manifest import tree_hash
from git_progressor.models import ProjectManifest, ProjectPlan
from git_progressor.planner.analyzer import Planner
from git_progressor.planner.contracts import PlanningRequest, SourceText
from git_progressor.planner.schema import plan_sha256
from git_progressor.security import CredentialScanner
from git_progressor.stages.filesystem import inspect_tree
from git_progressor.stages.generator import StageGenerator
from git_progressor.stages.validator import StageValidator
from git_progressor.storage.repositories import ProjectRepository

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class FileResponsePlanner:
    """Offline adapter for a recorded response; does not generate a plan itself."""

    def __init__(self, path: Path):
        self.path = path

    def create_plan(self, request: PlanningRequest) -> str:
        with self.path.open("rb") as stream:
            data = stream.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise InvalidPlanError("planner response exceeds byte limit")
        return data.decode("utf-8")


class PlanningService:
    def __init__(self, repository: ProjectRepository, limits: AnalyzerLimits):
        self.repository = repository
        self.analyzer = ProjectAnalyzer(limits)

    def prepare(
        self, project_id: UUID, revision: str | None = None
    ) -> tuple[PlanningRequest, ProjectManifest, Path]:
        record = self.repository.resolve_revision(project_id, revision)
        source = Path(record.source_path)
        manifest = ProjectManifest.model_validate_json(
            Path(record.manifest_path).read_text(encoding="utf-8")
        )
        if manifest.project_id != project_id or manifest.source_hash != record.source_hash:
            raise InvalidPlanError("revision identity mismatch")
        files = inspect_tree(source)
        if {p.relative_to(source).as_posix() for p in files} != {f.path for f in manifest.files}:
            raise InvalidPlanError("source inventory differs from manifest")
        CredentialScanner().assert_safe(source, files)
        analysis = self.analyzer.analyze(source, manifest)
        texts = []
        omitted = []
        remaining = 256 * 1024
        for entry in sorted(manifest.files, key=lambda item: item.path):
            if entry.size > min(64 * 1024, remaining):
                omitted.append(entry.path)
                continue
            data = (source / entry.path).read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                omitted.append(entry.path)
                continue
            if "\x00" in text:
                omitted.append(entry.path)
                continue
            texts.append(SourceText(path=entry.path, content=text))
            remaining -= len(data)
        request = PlanningRequest(
            context=PlannerContextBuilder().build(analysis),
            files=tuple(sorted(manifest.files, key=lambda item: item.path)),
            source_text=tuple(texts), omitted_paths=tuple(omitted),
        )
        return request, manifest, source

    def propose(
        self, project_id: UUID, provider: Planner, output: Path, revision: str | None = None
    ) -> ProjectPlan:
        if output.exists():
            raise InvalidPlanError("proposal output already exists")
        request, manifest, source = self.prepare(project_id, revision)
        raw = provider.create_plan(request)
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise InvalidPlanError("planner response must be bounded JSON text")
        try:
            plan = ProjectPlan.model_validate_json(raw)
        except ValidationError as exc:
            raise InvalidPlanError("planner response does not match the plan schema") from exc
        if len(plan.stages) > request.max_stages:
            raise InvalidPlanError("planner response exceeds stage limit")
        serialized = plan.model_dump_json().encode("utf-8")
        if any(pattern.search(serialized) for pattern in CredentialScanner.PATTERNS.values()):
            raise InvalidPlanError("suspected credentials in planner response metadata")
        output.parent.mkdir(parents=True, exist_ok=True)
        # Replay away from authoritative source and existing generated stages.
        with TemporaryDirectory(prefix="progressor-plan-") as directory:
            root = Path(directory)
            for entry in manifest.files:
                destination = root / "source" / entry.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / entry.path, destination)
            (root / "source").mkdir(exist_ok=True)
            snapshots = StageGenerator(root, project_id).generate(plan)
            previous_hash = tree_hash([])
            for stage, snapshot in zip(plan.stages, snapshots, strict=True):
                if snapshot.tree_hash == previous_hash:
                    raise InvalidPlanError(f"stage {stage.number} makes no filesystem change")
                previous_hash = snapshot.tree_hash
            report = StageValidator(root, manifest).validate(plan)
            if not report.valid:
                raise InvalidPlanError(
                    "proposal failed integrity, secret, or final-state validation"
                )
            artifact = {
                "schema_version": 1,
                "status": "VALIDATED",
                "validation_policy": "automatic-integrity-v1",
                "human_approval_required": False,
                "project_id": str(project_id),
                "source_revision": manifest.source_hash,
                "analysis_hash": request.context.analysis_hash,
                "plan_hash": plan_sha256(plan),
                "plan": plan.model_dump(mode="json"),
                "stage_hashes": [snapshot.tree_hash for snapshot in snapshots],
                "validation": "integrity-and-final-equality; runtime behavior not checked",
            }
            with output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(artifact, indent=2) + "\n")
        return plan
