import json

import pytest
from test_openai_planner import FakeClient
from test_preparation import worker_setup

from git_progressor.planner.openai_client import OpenAIPlanner
from git_progressor.services.live_planning import LivePlanningService
from git_progressor.storage.preparation import PreparationError


def arrange(tmp_path):
    worker, _, manifest, _, _ = worker_setup(tmp_path)
    service = LivePlanningService(worker)
    client = FakeClient()
    provider = OpenAIPlanner(client, model="test-model")
    kwargs = dict(model="test-model", max_output_tokens=8192, provider_factory=lambda: provider)
    return service, manifest.project_id, client, kwargs


def test_capture_usage_and_reuse_without_provider(tmp_path):
    service, project_id, client, kwargs = arrange(tmp_path)
    result = service.run(project_id, **kwargs)
    assert result["status"] == "SUCCEEDED"
    row, _ = service.request(project_id, model="test-model", max_output_tokens=8192)
    assert row["status"] == "CAPTURED"
    assert row["preparation_job_id"] == result["id"]
    assert json.loads(row["usage_json"])["total_tokens"] == 300

    def forbidden():
        pytest.fail("cached response must not require credentials or provider")

    kwargs["provider_factory"] = forbidden
    assert service.run(project_id, **kwargs) == result
    assert len(client.calls) == 1


def test_generation_failure_reuses_captured_response(tmp_path, monkeypatch):
    service, project_id, client, kwargs = arrange(tmp_path)
    original = service.worker.run

    def fail(*args, **kwargs):
        raise PreparationError("generation interrupted")

    monkeypatch.setattr(service.worker, "run", fail)
    with pytest.raises(PreparationError):
        service.run(project_id, **kwargs)
    monkeypatch.setattr(service.worker, "run", original)
    assert service.run(project_id, **kwargs)["status"] == "SUCCEEDED"
    assert len(client.calls) == 1


def test_interrupted_api_request_not_reissued(tmp_path):
    service, project_id, client, kwargs = arrange(tmp_path)

    def crash(**kwargs):
        client.calls.append(kwargs)
        raise KeyboardInterrupt()

    client.create = crash
    with pytest.raises(KeyboardInterrupt):
        service.run(project_id, **kwargs)
    with pytest.raises(PreparationError, match="STARTED"):
        service.run(project_id, **kwargs)
    assert len(client.calls) == 1


def test_refusal_usage_saved_and_no_retry(tmp_path):
    service, project_id, client, kwargs = arrange(tmp_path)
    client.result.status = "incomplete"
    with pytest.raises(PreparationError):
        service.run(project_id, **kwargs)
    with pytest.raises(PreparationError, match="FAILED"):
        service.run(project_id, **kwargs)
    row, _ = service.request(project_id, model="test-model", max_output_tokens=8192)
    assert json.loads(row["usage_json"])["total_tokens"] == 300
    assert row["response"] is None
    assert row["last_error"] == "PlannerResponseError:incomplete"
    assert len(client.calls) == 1


def test_configuration_failure_does_not_consume_attempt(tmp_path):
    service, project_id, client, kwargs = arrange(tmp_path)

    def missing():
        raise PreparationError("credentials missing")

    with pytest.raises(PreparationError):
        service.run(project_id, **(kwargs | {"provider_factory": missing}))
    row, _ = service.request(project_id, model="test-model", max_output_tokens=8192)
    assert row["status"] == "PENDING"
    assert service.run(project_id, **kwargs)["status"] == "SUCCEEDED"


def test_changed_captured_response_rejected(tmp_path):
    service, project_id, _, kwargs = arrange(tmp_path)
    service.run(project_id, **kwargs)
    row, _ = service.request(project_id, model="test-model", max_output_tokens=8192)
    with service.database.connect() as db:
        db.execute("UPDATE planning_requests SET response='changed' WHERE id=?", (row["id"],))
    with pytest.raises(PreparationError, match="integrity mismatch"):
        service.resume(row["id"])


def test_cli_live_handoff_uses_fake_client_once(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from git_progressor.cli import app
    from git_progressor.config import get_settings

    service, project_id, client, kwargs = arrange(tmp_path)
    monkeypatch.setattr("git_progressor.planner.openai_client.create_openai_planner",
                        lambda settings: kwargs["provider_factory"]())
    env = {"GIT_PROGRESSOR_DATA_DIR": str(tmp_path / "data"),
           "GIT_PROGRESSOR_DATABASE_URL": f"sqlite:///{tmp_path / 'state.db'}"}
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        command = ["prepare-openai", str(project_id), "--model", "test-model"]
        for _ in range(2):
            result = runner.invoke(app, command, env=env)
            assert result.exit_code == 0, result.output
            assert "SUCCEEDED" in result.output
        request_id = result.output.split("Planning request: ", 1)[1].splitlines()[0]
        result = runner.invoke(app, ["planning-status", request_id], env=env)
        assert result.exit_code == 0
        assert "300" in result.output
        result = runner.invoke(app, ["planning-resume", request_id], env=env)
        assert result.exit_code == 0, result.output
        assert len(client.calls) == 1
    finally:
        get_settings.cache_clear()


def test_explicit_retry_preserves_history_and_reuses_project(tmp_path):
    service, project_id, client, kwargs = arrange(tmp_path)
    client.result.status = "incomplete"
    with pytest.raises(PreparationError):
        service.run(project_id, **kwargs)
    row, _ = service.request(project_id, model="test-model", max_output_tokens=8192)
    client.result.status = "completed"
    result = service.retry_failed(row["id"], provider_factory=kwargs["provider_factory"])
    assert result["status"] == "SUCCEEDED"
    assert service.get(row["id"])["attempts"] == 2
    assert len(client.calls) == 2
    with service.database.connect() as db:
        history = db.execute("SELECT * FROM planning_retry_history").fetchall()
        assert len(history) == 1
        assert history[0]["last_error"] == "PlannerResponseError:incomplete"
        assert json.loads(history[0]["usage_json"])["total_tokens"] == 300
    with pytest.raises(PreparationError):
        service.retry_failed(row["id"], provider_factory=kwargs["provider_factory"])
    assert len(client.calls) == 2


def test_explicit_retry_has_attempt_limit(tmp_path):
    service, project_id, client, kwargs = arrange(tmp_path)
    client.result.status = "incomplete"
    with pytest.raises(PreparationError):
        service.run(project_id, **kwargs)
    row, _ = service.request(project_id, model="test-model", max_output_tokens=8192)
    for _ in range(3):
        with pytest.raises(PreparationError):
            service.retry_failed(row["id"], provider_factory=kwargs["provider_factory"])
    assert service.get(row["id"])["attempts"] == 3
    assert len(client.calls) == 3


def test_explicit_retry_cannot_repeat_uncertain_request(tmp_path):
    service, project_id, client, kwargs = arrange(tmp_path)
    row, _ = service.request(project_id, model="test-model", max_output_tokens=8192)
    with service.database.connect() as db:
        db.execute("UPDATE planning_requests SET status='STARTED',attempts=1 WHERE id=?",
                   (row["id"],))
    with pytest.raises(PreparationError):
        service.retry_failed(row["id"], provider_factory=kwargs["provider_factory"])
    assert not client.calls
