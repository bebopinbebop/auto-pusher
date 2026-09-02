from pathlib import Path
from typing import Annotated

import typer

from git_progressor.config import get_settings
from git_progressor.exceptions import GitProgressorError
from git_progressor.intake.service import ProjectImporter
from git_progressor.logging_config import configure_logging
from git_progressor.storage.database import SQLiteDatabase
from git_progressor.storage.repositories import ProjectRepository

app = typer.Typer(no_args_is_help=True, help="Plan and publish deterministic repository stages.")


def services() -> tuple[SQLiteDatabase, ProjectRepository]:
    settings = get_settings()
    database = SQLiteDatabase(settings.database_url)
    database.migrate()
    return database, ProjectRepository(database)


@app.command("import")
def import_project(path: Annotated[Path, typer.Argument(exists=True, file_okay=False)]) -> None:
    """Ingest a completed project into immutable local storage."""
    settings = get_settings()
    configure_logging(settings.log_level)
    _, repository = services()
    try:
        manifest = ProjectImporter(settings.data_dir, settings.max_file_bytes).ingest(path)
        manifest_path = settings.data_dir / "projects" / str(manifest.project_id) / "manifest.json"
        repository.add(manifest, str(manifest_path))
    except GitProgressorError as exc:
        typer.echo(f"Import failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(str(manifest.project_id))


@app.command()
def status() -> None:
    """List imported projects and their workflow state."""
    _, repository = services()
    rows = repository.list_projects()
    if not rows:
        typer.echo("No projects imported.")
    for row in rows:
        typer.echo(f"{row['id']}  {row['status']:<10}  {row['name']}")


@app.command()
def analyze(project_id: str) -> None:
    """Reserved for the future live planner integration."""
    typer.echo(f"Analysis is not implemented yet for {project_id}.", err=True)
    raise typer.Exit(2)


@app.command()
def publish(project_id: str, dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Reserved for deterministic publication; no Git operations are performed."""
    mode = "dry-run" if dry_run else "publish"
    typer.echo(
        f"{mode} is not implemented yet for {project_id}; no Git operation was performed.",
        err=True,
    )
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
