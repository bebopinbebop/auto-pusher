import json
from pathlib import Path
from uuid import UUID

from typer.testing import CliRunner

from git_progressor.analyzer.analyzer import ProjectAnalyzer
from git_progressor.analyzer.context import PlannerContextBuilder
from git_progressor.analyzer.models import AnalyzerLimits
from git_progressor.cli import app
from git_progressor.config import get_settings
from git_progressor.intake.manifest import build_manifest
from git_progressor.intake.multi import MultiProjectIngestor
from git_progressor.intake.scanner import scan_project
from git_progressor.intake.service import ProjectImporter
from git_progressor.storage.database import SQLiteDatabase
from git_progressor.storage.repositories import ProjectRepository

PROJECT_ID = UUID("00000000-0000-0000-0000-000000000456")


def limits(**changes: int) -> AnalyzerLimits:
    values = {
        "max_files": 100,
        "max_metadata_file_size": 4096,
        "max_analysis_bytes": 16384,
        "max_important_files": 20,
    }
    values.update(changes)
    return AnalyzerLimits(**values)


def manifest_for(root: Path):
    paths = scan_project(root, 1024 * 1024)
    return build_manifest(root, paths, PROJECT_ID)


def test_python_analysis_is_deterministic_and_detects_project_shape(tmp_path: Path) -> None:
    (tmp_path / "src/tool").mkdir(parents=True)
    (tmp_path / "tests/unit").mkdir(parents=True)
    (tmp_path / "tests/integration").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="tool"\ndependencies=["fastapi>=1"]\n'
        '[project.scripts]\ntool="tool.main:main"\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pytest==8\nflask>=3\n", encoding="utf-8")
    (tmp_path / "src/tool/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src/tool/main.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "tests/unit/test_main.py").write_text("def test_main(): pass\n", encoding="utf-8")
    (tmp_path / "tests/integration/test_api.py").write_text(
        "def test_api(): pass\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Tool\n", encoding="utf-8")
    (tmp_path / "docs/architecture.md").write_text("# Architecture\n", encoding="utf-8")
    manifest = manifest_for(tmp_path)
    analyzer = ProjectAnalyzer(limits())
    first = analyzer.analyze(tmp_path, manifest)
    second = analyzer.analyze(tmp_path, manifest)
    assert first == second
    assert first.analysis_hash == second.analysis_hash
    assert [item.name for item in first.languages] == ["Python"]
    assert {item.name for item in first.frameworks_and_tools} >= {"FastAPI", "Flask", "pytest"}
    assert first.tests.file_count == 2
    assert first.tests.unit_files == 1
    assert first.tests.integration_files == 1
    assert {item.path for item in first.modules} >= {"src/tool"}
    assert "pyproject.toml" in first.important_files


def test_javascript_typescript_dependencies_and_frameworks(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "web",
                "scripts": {"start": "do-not-print-this-command"},
                "dependencies": {"react": "1", "next": "2", "express": "3"},
                "devDependencies": {"jest": "4"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "src/index.ts").write_text("export const value = 1\n", encoding="utf-8")
    (tmp_path / "src/view.jsx").write_text("export default null\n", encoding="utf-8")
    (tmp_path / "src/view.test.ts").write_text("test('x', () => {})\n", encoding="utf-8")
    analysis = ProjectAnalyzer(limits()).analyze(tmp_path, manifest_for(tmp_path))
    assert {item.name for item in analysis.languages} >= {"JavaScript", "TypeScript"}
    assert {item.name for item in analysis.frameworks_and_tools} >= {
        "Express", "Jest", "Next.js", "Node.js", "React"
    }
    assert "do-not-print-this-command" not in analysis.model_dump_json()


def test_mixed_terraform_docker_actions_and_kubernetes(tmp_path: Path) -> None:
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / "infra/modules/network").mkdir(parents=True)
    (tmp_path / "k8s").mkdir()
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    (tmp_path / "script.ps1").write_text("Write-Host ok\n", encoding="utf-8")
    (tmp_path / "infra/main.tf").write_text("terraform {}\n", encoding="utf-8")
    (tmp_path / "infra/modules/network/main.tf").write_text("variable \"x\" {}\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / ".github/workflows/ci.yml").write_text("name: ci\n", encoding="utf-8")
    (tmp_path / "k8s/app.yaml").write_text("kind: Deployment\n", encoding="utf-8")
    analysis = ProjectAnalyzer(limits()).analyze(tmp_path, manifest_for(tmp_path))
    assert {item.name for item in analysis.languages} >= {
        "Go", "PowerShell", "HCL / Terraform", "YAML"
    }
    kinds = {item.kind for item in analysis.infrastructure}
    assert kinds >= {"terraform", "docker", "github-actions", "kubernetes"}
    assert {item.name for item in analysis.frameworks_and_tools} >= {
        "Docker", "Kubernetes", "Terraform"
    }


def test_cargo_dependencies_and_no_tests(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname="engine"\n[dependencies]\nserde="1"\n', encoding="utf-8"
    )
    (tmp_path / "src/main.rs").write_text("fn main() {}\n", encoding="utf-8")
    analysis = ProjectAnalyzer(limits()).analyze(tmp_path, manifest_for(tmp_path))
    assert [(item.ecosystem, item.name) for item in analysis.dependencies] == [("cargo", "serde")]
    assert not analysis.tests.present


def test_limits_and_secret_redaction_are_explicit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print('safe')\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("print('later')\n", encoding="utf-8")
    secret = "-----BEGIN PRIVATE KEY-----\nraw-secret-value"  # noqa: S105
    (tmp_path / "private.pem").write_text(secret, encoding="utf-8")
    (tmp_path / "package.json").write_text("{" + " " * 100 + "}", encoding="utf-8")
    manifest = build_manifest(tmp_path, sorted(tmp_path.iterdir()), PROJECT_ID)
    analysis = ProjectAnalyzer(
        limits(max_files=4, max_metadata_file_size=20, max_important_files=1)
    ).analyze(tmp_path, manifest)
    serialized = analysis.model_dump_json()
    assert "raw-secret-value" not in serialized
    assert "private.pem" not in analysis.important_files
    assert any("credential-shaped" in warning for warning in analysis.warnings)
    assert any("per-file limit" in warning for warning in analysis.warnings)
    assert analysis.statistics.important_files_selected <= 1


def test_changed_revision_changes_analysis_hash(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('one')\n", encoding="utf-8")
    analyzer = ProjectAnalyzer(limits())
    first = analyzer.analyze(tmp_path, manifest_for(tmp_path))
    (tmp_path / "app.py").write_text("print('two')\n", encoding="utf-8")
    second = analyzer.analyze(tmp_path, manifest_for(tmp_path))
    assert first.source_revision != second.source_revision
    assert first.analysis_hash != second.analysis_hash


def test_manifest_order_does_not_change_analysis(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("b = 2\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    manifest = manifest_for(tmp_path)
    reversed_manifest = manifest.model_copy(update={"files": tuple(reversed(manifest.files))})
    analyzer = ProjectAnalyzer(limits())
    assert analyzer.analyze(tmp_path, manifest) == analyzer.analyze(
        tmp_path, reversed_manifest
    )


def test_file_and_total_metadata_limits_record_warnings(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"limited","dependencies":{"react":"1"}}', encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="limited"\ndependencies=["pytest"]\n', encoding="utf-8"
    )
    (tmp_path / "z.py").write_text("value = 1\n", encoding="utf-8")
    manifest = manifest_for(tmp_path)
    file_limited = ProjectAnalyzer(limits(max_files=1)).analyze(tmp_path, manifest)
    byte_limited = ProjectAnalyzer(limits(max_analysis_bytes=1)).analyze(
        tmp_path, manifest
    )
    assert file_limited.statistics.skipped_files == 2
    assert any("file analysis limit" in warning for warning in file_limited.warnings)
    assert byte_limited.statistics.metadata_bytes_read == 0
    assert any("analysis byte limit" in warning for warning in byte_limited.warnings)


def test_planner_context_is_bounded_structured_metadata(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("unique-source-body\n", encoding="utf-8")
    analysis = ProjectAnalyzer(limits()).analyze(tmp_path, manifest_for(tmp_path))
    context = PlannerContextBuilder().build(analysis)
    assert context.analysis_hash == analysis.analysis_hash
    assert "unique-source-body" not in context.model_dump_json()


def test_service_selects_latest_or_explicit_revision_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    project = root / "tool"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname="revision-tool"\nversion="1"\n', encoding="utf-8"
    )
    (project / "app.py").write_text("print('one')\n", encoding="utf-8")
    database = SQLiteDatabase(f"sqlite:///{tmp_path / 'state.db'}")
    database.migrate()
    repository = ProjectRepository(database)
    ingestor = MultiProjectIngestor(ProjectImporter(tmp_path / "data", 1024), repository)
    first = ingestor.ingest(root).results[0]
    (project / "app.py").write_text("print('two')\n", encoding="utf-8")
    second = ingestor.ingest(root).results[0]
    from git_progressor.analyzer.service import AnalysisService

    service = AnalysisService(tmp_path / "data", repository, ProjectAnalyzer(limits()))
    latest = service.analyze(first.project_id)
    explicit = service.analyze(first.project_id, first.source_hash)
    repeated = service.analyze(first.project_id, first.source_hash)
    assert latest.source_revision == second.source_hash
    assert explicit == repeated
    assert explicit.source_revision == first.source_hash
    assert latest.analysis_hash != explicit.analysis_hash
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 2


def test_analyze_cli_and_invalid_revision(tmp_path: Path) -> None:
    runner = CliRunner()
    data_dir = tmp_path / "data"
    environment = {
        "GIT_PROGRESSOR_DATA_DIR": str(data_dir),
        "GIT_PROGRESSOR_DATABASE_URL": f"sqlite:///{(data_dir / 'state.db').as_posix()}",
    }
    source = tmp_path / "project"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        '[project]\nname="cli-analysis"\nversion="1"\n', encoding="utf-8"
    )
    (source / "app.py").write_text("do-not-print-source-body\n", encoding="utf-8")
    get_settings.cache_clear()
    imported = runner.invoke(app, ["import", str(source)], env=environment)
    assert imported.exit_code == 0, imported.output
    project_id = imported.output.strip()
    analyzed = runner.invoke(app, ["analyze", project_id], env=environment)
    assert analyzed.exit_code == 0, analyzed.output
    assert "RESULT: ANALYZED" in analyzed.output
    assert "do-not-print-source-body" not in analyzed.output
    invalid = runner.invoke(
        app, ["analyze", project_id, "--revision", "0" * 64], env=environment
    )
    assert invalid.exit_code == 1
    unknown = runner.invoke(app, ["analyze", str(UUID(int=999))], env=environment)
    assert unknown.exit_code == 1
