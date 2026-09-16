from pathlib import Path

from typer.testing import CliRunner

from git_progressor.cli import app
from git_progressor.config import get_settings
from git_progressor.storage.database import SQLiteDatabase

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_status_publication_progress(tmp_path: Path) -> None:
    runner = CliRunner()
    environment = cli_environment(tmp_path)
    get_settings.cache_clear()
    assert "No projects imported" in runner.invoke(app, ["status"], env=environment).output
    project_id = import_fixture(runner, environment)
    assert "Awaiting plan" in runner.invoke(app, ["status"], env=environment).output
    result = runner.invoke(
        app, ["generate", project_id, "--plan", str(FIXTURES / "calculator-plan.json")],
        env=environment,
    )
    assert result.exit_code == 0, result.output
    assert "Awaiting approval" in runner.invoke(app, ["status"], env=environment).output
    database = SQLiteDatabase(environment["GIT_PROGRESSOR_DATABASE_URL"])
    with database.connect() as connection:
        connection.execute("UPDATE plans SET approved_at = '2026-09-16T00:00:00Z'")
    assert "0%  0/5 stages published" in runner.invoke(app, ["status"], env=environment).output
    with database.connect() as connection:
        stages = connection.execute("SELECT id FROM stages ORDER BY stage_number").fetchall()
        for number, stage in enumerate(stages):
            connection.execute(
                """INSERT INTO publication_jobs
                (id, project_id, stage_id, publish_after, status, resulting_commit_sha, updated_at)
                VALUES (?, ?, ?, '2026-09-16T00:00:00Z', ?, ?, '2026-09-16T00:00:00Z')""",
                (str(number), project_id, stage["id"],
                 "FAILED" if number == 3 else "PUBLISHED", "a" * 40 if number < 4 else None),
            )
    result = runner.invoke(app, ["status"], env=environment)
    assert result.exit_code == 0, result.output
    assert "[############--------]  60%  3/5 stages published" in result.output
    assert project_id in result.output
    with database.connect() as connection:
        connection.execute(
            "UPDATE publication_jobs SET status = 'PUBLISHED', resulting_commit_sha = ?",
            ("b" * 40,),
        )
    assert "[####################] 100%  5/5" in runner.invoke(
        app, ["status"], env=environment,
    ).output


def cli_environment(tmp_path: Path) -> dict[str, str]:
    data_dir = tmp_path / "data"
    return {
        "GIT_PROGRESSOR_DATA_DIR": str(data_dir),
        "GIT_PROGRESSOR_DATABASE_URL": f"sqlite:///{(data_dir / 'state.db').as_posix()}",
    }


def import_fixture(runner: CliRunner, environment: dict[str, str]) -> str:
    get_settings.cache_clear()
    result = runner.invoke(
        app, ["import", str(FIXTURES / "calculator-final")], env=environment
    )
    assert result.exit_code == 0, result.output
    return result.output.strip()


def test_generate_and_validate_commands_persist_status(tmp_path: Path) -> None:
    runner = CliRunner()
    environment = cli_environment(tmp_path)
    project_id = import_fixture(runner, environment)
    generated = runner.invoke(
        app,
        ["generate", project_id, "--plan", str(FIXTURES / "calculator-plan.json")],
        env=environment,
    )
    assert generated.exit_code == 0, generated.output
    assert "Generated 5 deterministic stage snapshots" in generated.output

    validated = runner.invoke(app, ["validate", project_id], env=environment)
    assert validated.exit_code == 0, validated.output
    assert "RESULT: VALID" in validated.output

    database = SQLiteDatabase(environment["GIT_PROGRESSOR_DATABASE_URL"])
    with database.connect() as connection:
        statuses = [row[0] for row in connection.execute(
            "SELECT status FROM stages ORDER BY stage_number"
        )]
        project_status = connection.execute("SELECT status FROM projects").fetchone()[0]
    assert statuses == ["VALIDATED"] * 5
    assert project_status == "VALIDATED"

    regenerated = runner.invoke(app, ["generate", project_id], env=environment)
    assert regenerated.exit_code == 0, regenerated.output
    with database.connect() as connection:
        statuses = [row[0] for row in connection.execute(
            "SELECT status FROM stages ORDER BY stage_number"
        )]
    assert statuses == ["VALIDATED"] * 5


def test_validate_command_fails_after_corruption(tmp_path: Path) -> None:
    runner = CliRunner()
    environment = cli_environment(tmp_path)
    project_id = import_fixture(runner, environment)
    generated = runner.invoke(
        app,
        ["generate", project_id, "--plan", str(FIXTURES / "calculator-plan.json")],
        env=environment,
    )
    assert generated.exit_code == 0, generated.output
    final_file = tmp_path / "data" / "projects" / project_id / "stages/005/README.md"
    final_file.write_bytes(b"tampered\n")

    validated = runner.invoke(app, ["validate", project_id], env=environment)
    assert validated.exit_code == 1
    assert "RESULT: INVALID" in validated.output
    assert "README.md" in validated.output


def test_ingest_command_reports_multiple_projects(tmp_path: Path) -> None:
    runner = CliRunner()
    environment = cli_environment(tmp_path)
    root = tmp_path / "projects"
    for name in ("alpha", "beta"):
        project = root / name
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "1.0.0"\n', encoding="utf-8"
        )
        (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    get_settings.cache_clear()
    first = runner.invoke(app, ["ingest", str(root)], env=environment)
    assert first.exit_code == 0, first.output
    assert "Imported:      2" in first.output
    assert "Already known: 0" in first.output
    second = runner.invoke(app, ["ingest", str(root)], env=environment)
    assert second.exit_code == 0, second.output
    assert "Imported:      0" in second.output
    assert "Already known: 2" in second.output


def test_ingest_command_returns_failure_but_keeps_successes(tmp_path: Path) -> None:
    runner = CliRunner()
    environment = cli_environment(tmp_path)
    root = tmp_path / "projects"
    for name in ("good", "bad"):
        project = root / name
        project.mkdir(parents=True)
        (project / "package.json").write_text(
            f'{{"name":"{name}"}}', encoding="utf-8"
        )
    (root / "bad/private.key").write_text("not printed", encoding="utf-8")
    get_settings.cache_clear()
    result = runner.invoke(app, ["ingest", str(root)], env=environment)
    assert result.exit_code == 1
    assert "Imported:      1" in result.output
    assert "Failed:        1" in result.output
    database = SQLiteDatabase(environment["GIT_PROGRESSOR_DATABASE_URL"])
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
