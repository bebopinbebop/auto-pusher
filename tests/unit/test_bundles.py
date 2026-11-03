import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest
from test_preparation import worker_setup

from git_progressor.exceptions import InvalidPlanError
from git_progressor.services.bundles import export_bundle, verify_bundle


def test_portable_deterministic_export_and_replay(tmp_path):
    worker, job_id, manifest, _, _ = worker_setup(tmp_path)
    worker.run(job_id)
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    report = export_bundle(worker, job_id, first)
    assert export_bundle(worker, job_id, second) == report
    assert first.read_bytes() == second.read_bytes()
    assert verify_bundle(second, report["sha256"])["source_revision"] == manifest.source_hash
    assert report["stages"] == 5
    with pytest.raises(InvalidPlanError, match="already exists"):
        export_bundle(worker, job_id, first)
    with pytest.raises(InvalidPlanError, match="checksum"):
        verify_bundle(first, "0" * 64)


def test_incomplete_and_tampered_jobs_cannot_export(tmp_path):
    worker, job_id, _, _, _ = worker_setup(tmp_path)
    with pytest.raises(InvalidPlanError, match="completed"):
        export_bundle(worker, job_id, tmp_path / "bad.zip")
    result = worker.run(job_id)
    (Path(result["artifact_path"]) / "source/README.md").write_text("changed")
    with pytest.raises(InvalidPlanError, match="changed"):
        export_bundle(worker, job_id, tmp_path / "bad.zip")


def test_bundle_rejects_unexpected_paths_even_with_matching_digest(tmp_path):
    worker, job_id, _, _, _ = worker_setup(tmp_path)
    worker.run(job_id)
    path = tmp_path / "bundle.zip"
    export_bundle(worker, job_id, path)
    with ZipFile(path, "a") as archive:
        archive.writestr("../escape.txt", "unsafe")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(InvalidPlanError, match="unexpected"):
        verify_bundle(path, digest)
    assert not (tmp_path / "escape.txt").exists()
