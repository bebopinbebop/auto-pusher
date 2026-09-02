from datetime import UTC, datetime

from git_progressor.models import ProjectManifest, ProjectStatus
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

