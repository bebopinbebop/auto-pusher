from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from pydantic import ValidationError

from git_progressor.config import get_settings
from git_progressor.exceptions import GitProgressorError
from git_progressor.intake.service import ProjectImporter
from git_progressor.logging_config import configure_logging
from git_progressor.stages.generator import StageGenerator
from git_progressor.stages.validator import (
    StageValidator,
    load_project_manifest,
    load_project_plan,
    save_project_plan,
)
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


def project_context(project_id: str) -> tuple[UUID, Path, ProjectRepository]:
    try:
        identifier = UUID(project_id)
    except ValueError as exc:
        raise typer.BadParameter("project ID must be a UUID") from exc
    settings = get_settings()
    _, repository = services()
    repository.get(identifier)
    return identifier, settings.data_dir / "projects" / str(identifier), repository


@app.command()
def generate(
    project_id: str,
    plan_path: Annotated[
        Path | None,
        typer.Option("--plan", exists=True, dir_okay=False, help="Static plan JSON to persist."),
    ] = None,
) -> None:
    """Generate deterministic full snapshots from a validated static plan."""
    try:
        identifier, project_dir, repository = project_context(project_id)
        if plan_path is not None:
            plan = load_plan_file(plan_path)
            save_project_plan(project_dir, plan)
        else:
            plan = load_project_plan(project_dir)
        plan_id = repository.ensure_plan(identifier, plan)
        manifests = StageGenerator(project_dir, identifier).generate(plan)
        for manifest in manifests:
            manifest_path = project_dir / "stages" / f"{manifest.stage_number:03d}.manifest.json"
            repository.record_generated(plan_id, manifest, manifest_path)
    except (GitProgressorError, OSError, ValidationError) as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Generated {len(manifests)} deterministic stage snapshots.")
    for manifest in manifests:
        typer.echo(f"{manifest.stage_number:03d}  {manifest.tree_hash}")


def load_plan_file(path: Path):
    from git_progressor.models import ProjectPlan

    return ProjectPlan.model_validate_json(path.read_text(encoding="utf-8"))


@app.command()
def validate(project_id: str) -> None:
    """Independently validate snapshots and final-state equality."""
    try:
        identifier, project_dir, repository = project_context(project_id)
        plan = load_project_plan(project_dir)
        plan_id = repository.ensure_plan(identifier, plan)
        manifest = load_project_manifest(project_dir)
        report = StageValidator(project_dir, manifest).validate(plan)
        overall_error = None if report.valid else "independent project validation failed"
        for stage in report.stages:
            error_parts = [*stage.errors]
            if overall_error is not None:
                error_parts.append(overall_error)
            error = "; ".join(error_parts) if error_parts else None
            repository.record_validation(
                identifier, plan_id, stage.stage_number, stage.valid and report.valid, error
            )
    except (GitProgressorError, OSError, ValidationError) as exc:
        typer.echo(f"Validation failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Project: {report.project_name}")
    typer.echo(f"Stages: {len(report.stages)}\n")
    for stage in report.stages:
        typer.echo(f"{stage.stage_number:03d}  {'VALID' if stage.valid else 'INVALID'}")
        for error in stage.errors:
            typer.echo(f"     {error}")
    typer.echo("\nFinal-state verification:")
    typer.echo(f"  Missing:    {len(report.final_difference.missing)}")
    typer.echo(f"  Unexpected: {len(report.final_difference.unexpected)}")
    typer.echo(f"  Modified:   {len(report.final_difference.modified)}")
    for label, paths in (
        ("Missing", report.final_difference.missing),
        ("Unexpected", report.final_difference.unexpected),
        ("Modified", report.final_difference.modified),
    ):
        if paths:
            typer.echo(f"{label}:")
            for path in paths:
                typer.echo(f"  {path}")
    for error in report.errors:
        typer.echo(f"Error: {error}")
    typer.echo(f"\nSource tree hash: {report.source_tree_hash or 'unavailable'}")
    typer.echo(f"Final tree hash:  {report.final_tree_hash or 'unavailable'}")
    typer.echo(f"\nRESULT: {'VALID' if report.valid else 'INVALID'}")
    if not report.valid:
        raise typer.Exit(1)


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
