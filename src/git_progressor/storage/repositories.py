from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from git_progressor.exceptions import ProjectNotFoundError
from git_progressor.models import (
    ProjectManifest,
    ProjectPlan,
    ProjectStatus,
    StageManifest,
    StageStatus,
)
from git_progressor.planner.schema import plan_sha256
from git_progressor.storage.database import SQLiteDatabase


class ProjectRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def add(self, manifest: ProjectManifest, manifest_path: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO projects
                (id, name, source_hash, manifest_path, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(manifest.project_id), manifest.name, manifest.source_hash, manifest_path,
                 ProjectStatus.IMPORTED.value, manifest.created_at.isoformat(), now),
            )

    def list_projects(self) -> list[dict[str, str]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, source_hash, status, created_at FROM projects ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, project_id: UUID) -> dict[str, str]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (str(project_id),)
            ).fetchone()
        if row is None:
            raise ProjectNotFoundError(f"project does not exist: {project_id}")
        return dict(row)

    def ensure_plan(self, project_id: UUID, plan: ProjectPlan) -> str:
        canonical = plan.model_dump_json()
        plan_hash = plan_sha256(plan)
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM plans WHERE project_id = ? AND plan_hash = ?",
                (str(project_id), plan_hash),
            ).fetchone()
            if existing is not None:
                return str(existing[0])
            plan_id = str(uuid4())
            connection.execute(
                """INSERT INTO plans (id, project_id, plan_json, plan_hash, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (plan_id, str(project_id), canonical, plan_hash, now),
            )
            namespace = UUID(plan_id)
            for stage in plan.stages:
                connection.execute(
                    """INSERT INTO stages
                    (id, plan_id, stage_number, title, commit_message, status)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid5(namespace, str(stage.number))),
                        plan_id,
                        stage.number,
                        stage.title,
                        stage.suggested_commit_message,
                        StageStatus.PLANNED.value,
                    ),
                )
            connection.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (ProjectStatus.PLANNED.value, now, str(project_id)),
            )
        return plan_id

    def record_generated(
        self, plan_id: str, manifest: StageManifest, manifest_path: Path
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE stages SET snapshot_hash = ?, snapshot_path = ?, manifest_path = ?,
                status = CASE WHEN status IN ('VALIDATED', 'APPROVED') THEN status ELSE ? END,
                generated_at = COALESCE(generated_at, ?)
                WHERE plan_id = ? AND stage_number = ?""",
                (
                    manifest.tree_hash,
                    str(manifest_path.parent / f"{manifest.stage_number:03d}"),
                    str(manifest_path),
                    StageStatus.GENERATED.value,
                    now,
                    plan_id,
                    manifest.stage_number,
                ),
            )

    def record_validation(
        self, project_id: UUID, plan_id: str, stage_number: int, valid: bool, error: str | None
    ) -> None:
        now = datetime.now(UTC).isoformat()
        status = StageStatus.VALIDATED.value if valid else StageStatus.GENERATED.value
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE stages SET status = ?, validated_at = ?, validation_error = ?
                WHERE plan_id = ? AND stage_number = ?""",
                (status, now, error, plan_id, stage_number),
            )
            if valid:
                invalid_count = connection.execute(
                    "SELECT COUNT(*) FROM stages WHERE plan_id = ? AND status != ?",
                    (plan_id, StageStatus.VALIDATED.value),
                ).fetchone()[0]
                if invalid_count == 0:
                    connection.execute(
                        "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                        (ProjectStatus.VALIDATED.value, now, str(project_id)),
                    )
            else:
                connection.execute(
                    "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                    (ProjectStatus.PLANNED.value, now, str(project_id)),
                )
