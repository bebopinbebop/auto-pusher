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
    (3, """
    ALTER TABLE projects ADD COLUMN source_identity TEXT;
    ALTER TABLE projects ADD COLUMN identity_confidence TEXT;
    ALTER TABLE projects ADD COLUMN original_path TEXT;
    ALTER TABLE projects ADD COLUMN last_seen_path TEXT;
    ALTER TABLE projects ADD COLUMN last_seen_at TEXT;
    CREATE UNIQUE INDEX idx_projects_source_identity
        ON projects(source_identity) WHERE source_identity IS NOT NULL;
    CREATE TABLE source_revisions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        source_hash TEXT NOT NULL,
        manifest_path TEXT NOT NULL,
        source_path TEXT NOT NULL,
        observed_path TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        UNIQUE(project_id, source_hash)
    );
    CREATE INDEX idx_source_revisions_project
        ON source_revisions(project_id, imported_at);
    """),
    (4, """
    CREATE TABLE analyses (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        source_hash TEXT NOT NULL,
        analyzer_version INTEGER NOT NULL,
        analysis_hash TEXT NOT NULL,
        artifact_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(project_id, source_hash, analyzer_version)
    );
    CREATE INDEX idx_analyses_project_revision
        ON analyses(project_id, source_hash);
    """),
    (5, """
    CREATE TABLE preparation_jobs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        source_hash TEXT NOT NULL, response TEXT NOT NULL, response_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')),
        attempts INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until REAL,
        artifact_path TEXT, artifact_hash TEXT, last_error TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        UNIQUE(project_id, source_hash, response_hash)
    );
    """),
    (6, """
    CREATE TABLE planning_requests (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        source_hash TEXT NOT NULL, request_hash TEXT NOT NULL,
        model TEXT NOT NULL, max_output_tokens INTEGER NOT NULL,
        policy_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PENDING','STARTED','CAPTURED','FAILED')),
        response TEXT, response_hash TEXT, usage_json TEXT,
        preparation_job_id TEXT REFERENCES preparation_jobs(id),
        last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        UNIQUE(project_id,source_hash,request_hash,model,max_output_tokens,policy_version)
    );
    """),
    (7, """
    ALTER TABLE planning_requests ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
    UPDATE planning_requests SET attempts=1 WHERE status!='PENDING';
    CREATE TABLE planning_retry_history (
        request_id TEXT NOT NULL REFERENCES planning_requests(id),
        attempt INTEGER NOT NULL, status TEXT NOT NULL,
        last_error TEXT, usage_json TEXT, archived_at REAL NOT NULL,
        PRIMARY KEY(request_id,attempt)
    );
    """),
)
