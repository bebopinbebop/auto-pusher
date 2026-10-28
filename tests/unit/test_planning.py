import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from git_progressor.analyzer.models import AnalyzerLimits
from git_progressor.cli import app
from git_progressor.config import get_settings
from git_progressor.exceptions import InvalidPlanError, StageGenerationError
from git_progressor.intake.service import ProjectImporter
from git_progressor.planner.service import FileResponsePlanner, PlanningService
from git_progressor.storage.database import SQLiteDatabase
from git_progressor.storage.repositories import ProjectRepository

FIXTURES = Path(__file__).parents[1] / "fixtures"


def setup(tmp_path):
    importer = ProjectImporter(tmp_path / "data", 1024 * 1024)
    manifest = importer.ingest(FIXTURES / "calculator-final")
    database = SQLiteDatabase(f"sqlite:///{tmp_path / 'state.db'}")
    database.migrate()
    repository = ProjectRepository(database)
    root = tmp_path / "data/projects" / str(manifest.project_id)
    repository.add(manifest, str(root / "manifest.json"))
    limits = AnalyzerLimits(max_files=100, max_metadata_file_size=65536,
                            max_analysis_bytes=262144, max_important_files=25)
    return manifest, root, PlanningService(repository, limits)


def test_offline_plan_replays_and_is_revision_bound(tmp_path):
    manifest, root, service = setup(tmp_path)
    output = tmp_path / "proposal.json"
    provider = FileResponsePlanner(FIXTURES / "calculator-plan.json")
    plan = service.propose(manifest.project_id, provider, output)
    saved = json.loads(output.read_text())
    assert saved["status"] == "VALIDATED"
    assert saved["human_approval_required"] is False
    assert saved["validation_policy"] == "automatic-integrity-v1"
    assert saved["source_revision"] == manifest.source_hash
    assert saved["stage_hashes"][-1] == manifest.source_hash
    assert len(plan.stages) == 5
    assert not list((root / "stages").iterdir())
    with pytest.raises(InvalidPlanError, match="already exists"):
        service.propose(manifest.project_id, provider, output)
    request, _, _ = service.prepare(manifest.project_id)
    assert any(item.path == "calculator/core.py" for item in request.source_text)
    assert str(root) not in request.model_dump_json()


@pytest.mark.parametrize("mutation", ["malformed", "missing", "order", "final", "empty"])
def test_untrusted_response_rejected(tmp_path, mutation):
    manifest, _, service = setup(tmp_path)
    data = json.loads((FIXTURES / "calculator-plan.json").read_text())
    if mutation == "missing":
        del data["strategy"]
    elif mutation == "order":
        data["stages"][0]["number"] = 2
    elif mutation == "final":
        data["stages"] = data["stages"][:-1]
    elif mutation == "empty":
        data["stages"][0]["operations"] = []
    response = tmp_path / "response.json"
    response.write_text("not JSON" if mutation == "malformed" else json.dumps(data))
    output = tmp_path / "proposal.json"
    with pytest.raises((InvalidPlanError, StageGenerationError)):
        service.propose(manifest.project_id, FileResponsePlanner(response), output)
    assert not output.exists()


def test_cli_offline_planning(tmp_path):
    manifest, _, _ = setup(tmp_path)
    env = {"GIT_PROGRESSOR_DATA_DIR": str(tmp_path / "data"),
           "GIT_PROGRESSOR_DATABASE_URL": f"sqlite:///{tmp_path / 'state.db'}"}
    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["plan", str(manifest.project_id), "--response",
        str(FIXTURES / "calculator-plan.json"), "--output", str(tmp_path / "proposal.json")],
        env=env)
    assert result.exit_code == 0, result.output
    assert "no human approval required" in result.output
    assert "5 stages" in result.output
    get_settings.cache_clear()
