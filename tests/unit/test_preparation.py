from pathlib import Path

import pytest
from test_planning import FIXTURES, setup
from typer.testing import CliRunner

from git_progressor.cli import app
from git_progressor.config import get_settings
from git_progressor.services.preparation_service import PreparationWorker
from git_progressor.storage.database import SQLiteDatabase
from git_progressor.storage.preparation import PreparationError, PreparationJobs


def worker_setup(tmp_path):
    manifest, root, planning = setup(tmp_path)
    now = [1000.0]
    jobs = PreparationJobs(SQLiteDatabase(f"sqlite:///{tmp_path / 'state.db'}"),
                           clock=lambda: now[0])
    worker = PreparationWorker(jobs, planning, tmp_path / "data")
    job_id = worker.enqueue(manifest.project_id, FIXTURES / "calculator-plan.json")
    return worker, job_id, manifest, root, now


def test_retained_artifacts_and_duplicate_request(tmp_path):
    worker, job_id, manifest, _, _ = worker_setup(tmp_path)
    result = worker.run(job_id)
    assert result["status"] == "SUCCEEDED"
    root = Path(result["artifact_path"])
    assert (root / "stages/005/README.md").is_file()
    assert worker.enqueue(manifest.project_id, FIXTURES / "calculator-plan.json") == job_id
    assert worker.run(job_id) == result
    assert result["attempts"] == 1
    (root / "stages/005/README.md").write_text("tampered")
    with pytest.raises(PreparationError, match="changed"):
        worker.run(job_id)


def test_claim_exclusion_and_expired_owner_fenced(tmp_path):
    worker, job_id, _, _, now = worker_setup(tmp_path)
    owner = worker.jobs.claim(job_id)
    with pytest.raises(PreparationError):
        worker.jobs.claim(job_id)
    now[0] += 901
    new_owner = worker.jobs.claim(job_id)
    with pytest.raises(PreparationError, match="lease lost"):
        worker.jobs.finish(job_id, owner, error="stale")
    worker.jobs.finish(job_id, new_owner, error="test")
    assert worker.jobs.get(job_id)["attempts"] == 2


def test_interruption_rebuilds_private_attempt(tmp_path, monkeypatch):
    worker, job_id, _, _, now = worker_setup(tmp_path)
    original = worker.jobs.finish

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(worker.jobs, "finish", interrupt)
    with pytest.raises(KeyboardInterrupt):
        worker.run(job_id)
    assert worker.jobs.get(job_id)["status"] == "RUNNING"
    monkeypatch.setattr(worker.jobs, "finish", original)
    now[0] += 901
    result = worker.run(job_id)
    assert result["status"] == "SUCCEEDED"
    assert result["attempts"] == 2
    assert len(list((tmp_path / "data/preparations" / job_id).iterdir())) == 2


def test_invalid_response_bounded_retries_and_sanitized_error(tmp_path):
    worker, _, manifest, _, _ = worker_setup(tmp_path)
    response = tmp_path / "bad.json"
    response.write_text("private text not JSON")
    job_id = worker.enqueue(manifest.project_id, response)
    for attempt in range(3):
        with pytest.raises(PreparationError):
            worker.run(job_id, retry=attempt > 0)
        job = worker.jobs.get(job_id)
        assert job["status"] == "FAILED"
        assert job["artifact_path"] is None
        assert job["last_error"] == "InvalidPlanError"
    with pytest.raises(PreparationError):
        worker.run(job_id, retry=True)
    assert worker.jobs.get(job_id)["attempts"] == 3


def test_source_tampering_rejected(tmp_path):
    worker, job_id, _, root, _ = worker_setup(tmp_path)
    source = root / "source/calculator/core.py"
    source.chmod(0o600)  # Simulate corruption of this test's imported source only.
    source.write_text("changed")
    with pytest.raises(PreparationError):
        worker.run(job_id)
    assert worker.jobs.get(job_id)["status"] == "FAILED"


def test_response_captured_at_enqueue(tmp_path):
    worker, _, manifest, _, _ = worker_setup(tmp_path)
    response = tmp_path / "response.json"
    response.write_bytes((FIXTURES / "calculator-plan.json").read_bytes())
    job_id = worker.enqueue(manifest.project_id, response)
    response.write_text("subsequent edits do not change queued input")
    assert worker.run(job_id)["status"] == "SUCCEEDED"


def test_failed_job_requires_explicit_retry(tmp_path):
    worker, job_id, _, _, _ = worker_setup(tmp_path)
    owner = worker.jobs.claim(job_id)
    worker.jobs.finish(job_id, owner, error="Interrupted")
    with pytest.raises(PreparationError):
        worker.run(job_id)
    assert worker.jobs.get(job_id)["attempts"] == 1
    assert worker.run(job_id, retry=True)["status"] == "SUCCEEDED"


def test_missing_completed_artifacts_rejected(tmp_path):
    worker, job_id, _, _, _ = worker_setup(tmp_path)
    job = worker.run(job_id)
    (Path(job["artifact_path"]) / "proposal.json").unlink()
    with pytest.raises(PreparationError, match="changed"):
        worker.run(job_id)


def test_concurrent_claims_have_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    worker, job_id, _, _, _ = worker_setup(tmp_path)
    barrier = Barrier(2)

    def claim():
        barrier.wait()
        try:
            return worker.jobs.claim(job_id)
        except PreparationError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert worker.jobs.get(job_id)["attempts"] == 1


def test_cli_preparation(tmp_path):
    worker, job_id, manifest, _, _ = worker_setup(tmp_path)
    env = {"GIT_PROGRESSOR_DATA_DIR": str(tmp_path / "data"),
           "GIT_PROGRESSOR_DATABASE_URL": f"sqlite:///{tmp_path / 'state.db'}"}
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        result = runner.invoke(app, ["prepare", str(manifest.project_id), "--response",
                               str(FIXTURES / "calculator-plan.json")], env=env)
        assert result.exit_code == 0, result.output
        assert "SUCCEEDED" in result.output
        status = runner.invoke(app, ["preparation-status", job_id], env=env)
        assert "Attempts: 1/3" in status.output
        result = runner.invoke(app, ["prepare-resume", job_id], env=env)
        assert result.exit_code == 0, result.output
        assert worker.jobs.get(job_id)["attempts"] == 1
    finally:
        get_settings.cache_clear()
