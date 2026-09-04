from pathlib import Path

from git_progressor.storage.database import SQLiteDatabase


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    database = SQLiteDatabase(f"sqlite:///{tmp_path / 'state.db'}")
    database.migrate()
    database.migrate()
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert {"projects", "plans", "stages", "publication_jobs", "locks"} <= tables
    assert version == 2
    with database.connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(stages)")}
    assert {"manifest_path", "generated_at", "validated_at", "validation_error"} <= columns
