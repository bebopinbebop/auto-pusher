"""Offline preparation worker; no network calls or project code execution."""
import hashlib
import json
import shutil
from pathlib import Path
from uuid import UUID

from git_progressor.planner.service import MAX_RESPONSE_BYTES, FileResponsePlanner
from git_progressor.security import CredentialScanner
from git_progressor.stages.filesystem import inspect_tree
from git_progressor.stages.generator import StageGenerator
from git_progressor.stages.validator import StageValidator
from git_progressor.storage.preparation import PreparationError


def artifact_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise PreparationError("preparation artifacts missing or unsafe")
    entries = [(p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
               for p in inspect_tree(root)]
    return hashlib.sha256(json.dumps(sorted(entries)).encode()).hexdigest()


class PreparationWorker:
    def __init__(self, jobs, planning, data_dir: Path):
        self.jobs = jobs
        self.planning = planning
        self.data_dir = data_dir

    def enqueue(self, project_id: UUID, response_path: Path, revision=None) -> str:
        with response_path.open("rb") as stream:
            raw = stream.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PreparationError("response exceeds byte limit")
        if any(pattern.search(raw) for pattern in CredentialScanner.PATTERNS.values()):
            raise PreparationError("suspected credentials in response")
        record = self.planning.repository.resolve_revision(project_id, revision)
        return self.jobs.enqueue(project_id, record.source_hash, raw.decode("utf-8"))

    def run(self, job_id: str, *, retry=False):
        job = self.jobs.get(job_id)
        if job["status"] == "SUCCEEDED":
            if artifact_digest(Path(job["artifact_path"])) != job["artifact_hash"]:
                raise PreparationError("completed preparation artifacts changed")
            return job
        owner = self.jobs.claim(job_id, retry=retry)
        # Each attempt has a private output. Only the fenced database pointer publishes it.
        root = self.data_dir / "preparations" / job_id / owner
        try:
            if hashlib.sha256(job["response"].encode()).hexdigest() != job["response_hash"]:
                raise PreparationError("queued response integrity mismatch")
            root.mkdir(parents=True, exist_ok=False)
            response = root / "response.json"
            response.write_text(job["response"], encoding="utf-8")
            identifier = UUID(job["project_id"])
            plan = self.planning.propose(
                identifier, FileResponsePlanner(response), root / "proposal.json",
                job["source_hash"],
            )
            _, manifest, source = self.planning.prepare(identifier, job["source_hash"])
            (root / "source").mkdir()
            for entry in manifest.files:
                target = root / "source" / entry.path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / entry.path, target)
            (root / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
            StageGenerator(root, identifier).generate(plan)
            if not StageValidator(root, manifest).validate(plan).valid:
                raise PreparationError("retained stages failed validation")
            self.jobs.finish(job_id, owner, path=str(root.resolve()), digest=artifact_digest(root))
        except Exception as exc:
            # Do not persist exception messages: they may include source or credentials.
            try:
                self.jobs.finish(job_id, owner, error=type(exc).__name__)
            except PreparationError:
                pass
            raise PreparationError("preparation failed; inspect job status") from exc
        return self.jobs.get(job_id)
