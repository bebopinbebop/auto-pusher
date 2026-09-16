from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from git_progressor.analyzer.models import AnalysisRecord
from git_progressor.exceptions import ProjectNotFoundError
from git_progressor.models import (
    ProjectManifest,
    ProjectPlan,
    ProjectRecord,
    ProjectStatus,
    SourceRevisionRecord,
    StageManifest,
    StageStatus,
)
from git_progressor.planner.schema import plan_sha256
from git_progressor.storage.database import SQLiteDatabase


class ProjectRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def add(
        self,
        manifest: ProjectManifest,
        manifest_path: str,
        source_identity: str | None = None,
        identity_confidence: str | None = None,
        observed_path: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO projects
                (id, name, source_hash, manifest_path, status, created_at, updated_at,
                 source_identity, identity_confidence, original_path, last_seen_path, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(manifest.project_id),
                    manifest.name,
                    manifest.source_hash,
                    manifest_path,
                    ProjectStatus.IMPORTED.value,
                    manifest.created_at.isoformat(),
                    now,
                    source_identity,
                    identity_confidence,
                    observed_path,
                    observed_path,
                    now if observed_path else None,
                ),
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

    def publication_progress(self, project_id: str) -> tuple[bool, int, int] | None:
        """Report the latest plan, counting only confirmed publication jobs."""
        with self.database.connect() as connection:
            plan = connection.execute(
                """SELECT id, approved_at FROM plans WHERE project_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
            if plan is None:
                return None
            counts = connection.execute(
                """SELECT COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN j.status = 'PUBLISHED'
                    AND NULLIF(TRIM(j.resulting_commit_sha), '') IS NOT NULL
                    THEN 1 ELSE 0 END), 0) AS published
                FROM stages s LEFT JOIN publication_jobs j
                    ON j.stage_id = s.id AND j.project_id = ?
                WHERE s.plan_id = ?""",
                (project_id, plan["id"]),
            ).fetchone()
        return bool(plan["approved_at"]), counts["published"], counts["total"]

    def find_by_source_identity(self, source_identity: str) -> ProjectRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE source_identity = ?", (source_identity,)
            ).fetchone()
        return self._project_record(row) if row is not None else None

    def find_revision(
        self, project_id: UUID, source_hash: str
    ) -> SourceRevisionRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT * FROM source_revisions
                WHERE project_id = ? AND source_hash = ?""",
                (str(project_id), source_hash),
            ).fetchone()
        if row is None:
            return None
        return SourceRevisionRecord(
            revision_id=UUID(row["id"]),
            project_id=UUID(row["project_id"]),
            source_hash=row["source_hash"],
            manifest_path=row["manifest_path"],
            source_path=row["source_path"],
            observed_path=row["observed_path"],
            imported_at=datetime.fromisoformat(row["imported_at"]),
        )

    def add_revision(
        self,
        project_id: UUID,
        source_hash: str,
        manifest_path: Path,
        source_path: Path,
        observed_path: Path,
    ) -> SourceRevisionRecord:
        now = datetime.now(UTC)
        revision_id = uuid5(project_id, source_hash)
        with self.database.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO source_revisions
                (id, project_id, source_hash, manifest_path, source_path,
                 observed_path, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(revision_id),
                    str(project_id),
                    source_hash,
                    str(manifest_path),
                    str(source_path),
                    str(observed_path),
                    now.isoformat(),
                ),
            )
        record = self.find_revision(project_id, source_hash)
        if record is None:
            raise RuntimeError("source revision was not persisted")
        return record

    def mark_seen(self, project_id: UUID, path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE projects SET last_seen_path = ?, last_seen_at = ?, updated_at = ?
                WHERE id = ?""",
                (str(path), now, now, str(project_id)),
            )

    def resolve_revision(
        self, project_id: UUID, source_hash: str | None = None
    ) -> SourceRevisionRecord:
        self.get(project_id)
        with self.database.connect() as connection:
            if source_hash is None:
                row = connection.execute(
                    """SELECT * FROM source_revisions WHERE project_id = ?
                    ORDER BY imported_at DESC, id DESC LIMIT 1""",
                    (str(project_id),),
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT * FROM source_revisions
                    WHERE project_id = ? AND source_hash = ?""",
                    (str(project_id), source_hash),
                ).fetchone()
            if row is not None:
                return self.find_revision(project_id, row["source_hash"])  # type: ignore[return-value]
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (str(project_id),)
            ).fetchone()
        if project is None or (
            source_hash is not None and source_hash != project["source_hash"]
        ):
            raise ProjectNotFoundError(
                f"source revision does not exist for project {project_id}: {source_hash}"
            )
        project_dir = Path(project["manifest_path"]).parent
        return SourceRevisionRecord(
            revision_id=uuid5(project_id, project["source_hash"]),
            project_id=project_id,
            source_hash=project["source_hash"],
            manifest_path=project["manifest_path"],
            source_path=str(project_dir / "source"),
            observed_path=project["original_path"] or "",
            imported_at=datetime.fromisoformat(project["created_at"]),
        )

    def record_analysis(
        self,
        project_id: UUID,
        source_hash: str,
        analyzer_version: int,
        analysis_hash: str,
        artifact_path: Path,
    ) -> AnalysisRecord:
        now = datetime.now(UTC)
        analysis_id = uuid5(project_id, f"analysis:{source_hash}:{analyzer_version}")
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO analyses
                (id, project_id, source_hash, analyzer_version, analysis_hash,
                 artifact_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, source_hash, analyzer_version) DO UPDATE SET
                    analysis_hash = excluded.analysis_hash,
                    artifact_path = excluded.artifact_path""",
                (
                    str(analysis_id),
                    str(project_id),
                    source_hash,
                    analyzer_version,
                    analysis_hash,
                    str(artifact_path),
                    now.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM analyses WHERE id = ?", (str(analysis_id),)
            ).fetchone()
        return AnalysisRecord(
            analysis_id=analysis_id,
            project_id=project_id,
            source_revision=row["source_hash"],
            analyzer_version=row["analyzer_version"],
            analysis_hash=row["analysis_hash"],
            artifact_path=row["artifact_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _project_record(row) -> ProjectRecord:
        return ProjectRecord(
            project_id=UUID(row["id"]),
            name=row["name"],
            source_identity=row["source_identity"],
            identity_confidence=(
                row["identity_confidence"] if row["identity_confidence"] else None
            ),
            source_hash=row["source_hash"],
            status=ProjectStatus(row["status"]),
            original_path=row["original_path"],
            last_seen_path=row["last_seen_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_seen_at=(
                datetime.fromisoformat(row["last_seen_at"])
                if row["last_seen_at"]
                else None
            ),
        )

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
