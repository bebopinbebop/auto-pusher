"""Portable source + declarative plan bundles, independently replayed on verification."""
import hashlib
import json
import shutil
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from git_progressor.exceptions import InvalidPlanError
from git_progressor.intake.manifest import tree_hash
from git_progressor.models import ProjectManifest, ProjectPlan
from git_progressor.planner.service import validate_operation_order
from git_progressor.security import CredentialScanner
from git_progressor.services.preparation_service import artifact_digest
from git_progressor.stages.generator import StageGenerator
from git_progressor.stages.validator import StageValidator

MAX_BUNDLE_BYTES = 100 * 1024 * 1024
MAX_ENTRIES = 10000


def verify_bundle(path: Path, expected_sha256: str) -> dict:
    """Verify a trusted external digest, then replay in isolated temporary storage."""
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise InvalidPlanError("bundle exceeds size limit")
    with path.open("rb") as stream:
        data = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(data) > MAX_BUNDLE_BYTES:
        raise InvalidPlanError("bundle exceeds size limit")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise InvalidPlanError("bundle checksum mismatch")
    try:
        with (
            ZipFile(BytesIO(data)) as archive,
            TemporaryDirectory(prefix="progressor-bundle-") as tmp,
        ):
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (len(entries) > MAX_ENTRIES or len(names) != len(set(names))
                    or sum(entry.file_size for entry in entries) > MAX_BUNDLE_BYTES
                    or any(entry.is_dir() or entry.flag_bits & 1 for entry in entries)):
                raise InvalidPlanError("invalid bundle inventory or size")
            manifest = ProjectManifest.model_validate_json(archive.read("manifest.json"))
            plan = ProjectPlan.model_validate_json(archive.read("plan.json"))
            metadata = manifest.model_dump_json().encode() + plan.model_dump_json().encode()
            if any(pattern.search(metadata) for pattern in CredentialScanner.PATTERNS.values()):
                raise InvalidPlanError("suspected credentials in bundle metadata")
            allowed = {"manifest.json", "plan.json"} | {
                "source/" + entry.path for entry in manifest.files
            }
            if set(names) != allowed:
                raise InvalidPlanError("unexpected or missing bundle entries")
            validate_operation_order(plan, manifest)
            root = Path(tmp)
            (root / "source").mkdir()
            for entry in manifest.files:
                data = archive.read("source/" + entry.path)
                if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
                    raise InvalidPlanError("bundle source file mismatch")
                destination = root / "source" / entry.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            snapshots = StageGenerator(root, manifest.project_id).generate(plan)
            previous = tree_hash([])
            for snapshot in snapshots:
                if snapshot.tree_hash == previous:
                    raise InvalidPlanError("bundle contains an unchanged stage")
                previous = snapshot.tree_hash
            report = StageValidator(root, manifest).validate(plan)
            if not report.valid:
                raise InvalidPlanError("bundle failed independent validation")
            return {"sha256": digest, "project_id": str(manifest.project_id),
                    "source_revision": manifest.source_hash, "stages": len(plan.stages)}
    except (BadZipFile, KeyError) as exc:
        raise InvalidPlanError("invalid bundle archive") from exc


def export_bundle(worker, job_id: str, output: Path) -> dict:
    """Export only a completed job; never run preparation or call a model here."""
    job = worker.jobs.get(job_id)
    if job["status"] != "SUCCEEDED":
        raise InvalidPlanError("only completed preparation jobs can be exported")
    root = Path(job["artifact_path"])
    if artifact_digest(root) != job["artifact_hash"]:
        raise InvalidPlanError("preparation artifacts changed")
    if output.exists():
        raise InvalidPlanError("bundle destination already exists")
    manifest = ProjectManifest.model_validate_json((root / "manifest.json").read_bytes())
    proposal = json.loads((root / "proposal.json").read_text(encoding="utf-8"))
    plan = ProjectPlan.model_validate(proposal["plan"])
    payloads = {"manifest.json": manifest.model_dump_json().encode(),
                "plan.json": plan.model_dump_json().encode()}
    for entry in manifest.files:
        payloads["source/" + entry.path] = (root / "source" / entry.path).read_bytes()
    if sum(map(len, payloads.values())) > MAX_BUNDLE_BYTES or len(payloads) > MAX_ENTRIES:
        raise InvalidPlanError("bundle exceeds export limits")
    with TemporaryDirectory(prefix="progressor-export-") as tmp:
        temporary = Path(tmp) / "bundle.zip"
        with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
            for name, data in sorted(payloads.items()):
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                archive.writestr(info, data)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        report = verify_bundle(temporary, digest)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as target, temporary.open("rb") as source:
            shutil.copyfileobj(source, target)
    return report
