from types import SimpleNamespace

import pytest
from test_planning import FIXTURES, setup

from git_progressor.config import Settings
from git_progressor.exceptions import InvalidPlanError, PlannerRequestError, PlannerResponseError
from git_progressor.planner.openai_client import (
    OpenAIPlanner,
    create_openai_planner,
    response_schema,
)


class FakeClient:
    def __init__(self, **overrides):
        self.responses = self
        self.calls = []
        self.result = SimpleNamespace(
            **({"status": "completed", "output": [],
                "output_text": (FIXTURES / "calculator-plan.json").read_text(),
                "usage": SimpleNamespace(input_tokens=100, output_tokens=200, total_tokens=300)}
               | overrides)
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_adapter_replays_through_integrity_validation(tmp_path):
    manifest, _, service = setup(tmp_path)
    client = FakeClient()
    planner = OpenAIPlanner(client, model="test-model")
    plan = service.propose(manifest.project_id, planner, tmp_path / "proposal.json")
    assert len(plan.stages) == 5
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["store"] is False
    assert call["max_output_tokens"] == 8192
    assert call["text"]["format"]["strict"] is True
    assert "tools" not in call
    assert planner.last_usage["total_tokens"] == 300


@pytest.mark.parametrize("overrides", [
    {"status": "incomplete"}, {"status": "failed"}, {"output_text": ""},
    {"output_text": "not JSON"}, {"output_text": "x" * (2 * 1024 * 1024 + 1)},
    {"output": [SimpleNamespace(content=[SimpleNamespace(type="refusal")])]},
])
def test_bad_responses_rejected(tmp_path, overrides):
    manifest, _, service = setup(tmp_path)
    client = FakeClient(**overrides)
    output = tmp_path / "proposal.json"
    with pytest.raises(InvalidPlanError):
        service.propose(manifest.project_id, OpenAIPlanner(client, model="test"), output)
    assert len(client.calls) == 1
    assert not output.exists()


def test_input_limit_prevents_request(tmp_path):
    manifest, _, service = setup(tmp_path)
    client = FakeClient()
    request, _, _ = service.prepare(manifest.project_id)
    with pytest.raises(InvalidPlanError, match="input exceeds"):
        OpenAIPlanner(client, model="test", max_input_bytes=1).create_plan(request)
    assert not client.calls


def test_schema_diagnostic_does_not_expose_response(tmp_path):
    manifest, _, service = setup(tmp_path)
    request, _, _ = service.prepare(manifest.project_id)
    client = FakeClient(output_text='{"private_model_text": "do not log this"}')
    with pytest.raises(PlannerResponseError) as error:
        OpenAIPlanner(client, model="test").create_plan(request)
    assert error.value.category == "schema"
    assert "private_model_text" not in str(error.value)
    assert "do not log this" not in str(error.value)
    assert PlannerResponseError("sensitive detail").category == "unknown"


def test_api_error_redacted_without_retry(tmp_path):
    manifest, _, service = setup(tmp_path)
    client = FakeClient()

    def fail(**kwargs):
        client.calls.append(kwargs)
        raise RuntimeError("sensitive provider message")

    client.create = fail
    request, _, _ = service.prepare(manifest.project_id)
    with pytest.raises(InvalidPlanError, match="no automatic retry") as error:
        OpenAIPlanner(client, model="test").create_plan(request)
    assert "sensitive" not in str(error.value)
    assert len(client.calls) == 1


def test_wire_schema_requires_all_fields():
    schema = response_schema()
    for item in [schema, *schema["$defs"].values()]:
        if item.get("type") == "object":
            assert set(item["required"]) == set(item["properties"])
            assert item["additionalProperties"] is False
            assert all("default" not in value for value in item["properties"].values())


@pytest.mark.parametrize("status,category", [
    (400, "bad_request"), (401, "authentication"), (403, "permission"),
    (404, "not_found"), (429, "rate_or_quota"), (503, "server"), (None, "unknown"),
])
def test_provider_diagnostics_are_allowlisted(tmp_path, status, category):
    manifest, _, service = setup(tmp_path)
    client = FakeClient()

    def fail(**kwargs):
        exc = RuntimeError("private credential and repository data")
        exc.status_code = status
        raise exc

    client.create = fail
    request, _, _ = service.prepare(manifest.project_id)
    with pytest.raises(PlannerRequestError) as error:
        OpenAIPlanner(client, model="test").create_plan(request)
    assert error.value.category == category
    assert "private" not in str(error.value)


def test_factory_requires_explicit_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(InvalidPlanError, match="explicit OpenAI model"):
        create_openai_planner(Settings(_env_file=None, openai_model=None))
    with pytest.raises(InvalidPlanError, match="process environment"):
        create_openai_planner(Settings(_env_file=None, openai_model="test"))
