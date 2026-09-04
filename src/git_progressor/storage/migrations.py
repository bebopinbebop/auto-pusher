MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, """
    CREATE TABLE projects (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, source_hash TEXT NOT NULL,
        manifest_path TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('IMPORTED','PLANNED','VALIDATED','APPROVED','PAUSED')
        ),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE plans (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        plan_json TEXT NOT NULL, plan_hash TEXT NOT NULL, approved_at TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE stages (
        id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id),
        stage_number INTEGER NOT NULL CHECK (stage_number > 0), title TEXT NOT NULL,
        snapshot_hash TEXT, snapshot_path TEXT, commit_message TEXT NOT NULL, status TEXT NOT NULL,
        UNIQUE(plan_id, stage_number)
    );
    CREATE TABLE repositories (
        project_id TEXT PRIMARY KEY REFERENCES projects(id), remote_url TEXT NOT NULL,
        branch TEXT NOT NULL, expected_head_sha TEXT
    );
    CREATE TABLE publication_jobs (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        stage_id TEXT NOT NULL UNIQUE REFERENCES stages(id), publish_after TEXT NOT NULL,
        status TEXT NOT NULL, expected_parent_sha TEXT, resulting_commit_sha TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0, last_error TEXT, updated_at TEXT NOT NULL
    );
    CREATE TABLE publication_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES publication_jobs(id),
        started_at TEXT NOT NULL, finished_at TEXT, expected_parent_sha TEXT,
        resulting_commit_sha TEXT, result TEXT NOT NULL, error TEXT
    );
    CREATE TABLE locks (
        project_id TEXT PRIMARY KEY REFERENCES projects(id), owner_id TEXT NOT NULL,
        acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL
    );
    CREATE INDEX idx_jobs_due ON publication_jobs(status, publish_after);
    """),
    (2, """
    ALTER TABLE stages ADD COLUMN manifest_path TEXT;
    ALTER TABLE stages ADD COLUMN generated_at TEXT;
    ALTER TABLE stages ADD COLUMN validated_at TEXT;
    ALTER TABLE stages ADD COLUMN validation_error TEXT;
    CREATE INDEX idx_stages_status ON stages(status);
    """),
)
