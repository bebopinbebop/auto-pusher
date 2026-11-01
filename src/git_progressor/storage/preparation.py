"""Durable local jobs. Lease tokens fence stale workers from recording results."""
import hashlib
import time
from uuid import uuid4

from git_progressor.exceptions import GitProgressorError
from git_progressor.storage.database import SQLiteDatabase


class PreparationError(GitProgressorError):
    pass


class PreparationJobs:
    def __init__(self, database: SQLiteDatabase, clock=time.time):
        self.database = database
        self.clock = clock

    def enqueue(self, project_id, source_hash: str, response: str) -> str:
        digest = hashlib.sha256(response.encode()).hexdigest()
        now = self.clock()
        with self.database.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO preparation_jobs "
                "(id,project_id,source_hash,response,response_hash,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,'PENDING',?,?)",
                (str(uuid4()), str(project_id), source_hash, response, digest, now, now),
            )
            return db.execute(
                "SELECT id FROM preparation_jobs WHERE project_id=? AND source_hash=? "
                "AND response_hash=?", (str(project_id), source_hash, digest),
            ).fetchone()[0]

    def get(self, job_id: str):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM preparation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise PreparationError("unknown preparation job")
        return dict(row)

    def claim(self, job_id: str, *, retry=False, lease_seconds=900) -> str:
        if lease_seconds <= 0:
            raise ValueError("lease must be positive")
        owner, now = str(uuid4()), self.clock()
        with self.database.connect() as db:
            result = db.execute(
                "UPDATE preparation_jobs SET status='RUNNING',owner=?,lease_until=?,"
                "attempts=attempts+1,updated_at=?,last_error=NULL WHERE id=? AND attempts<3 "
                "AND (status='PENDING' OR (status='RUNNING' AND lease_until<=?) "
                "OR (status='FAILED' AND ?))",
                (owner, now + lease_seconds, now, job_id, now, retry),
            )
            if result.rowcount != 1:
                raise PreparationError("job busy, finished, or retry limit reached")
        return owner

    def finish(self, job_id, owner, *, path=None, digest=None, error=None):
        if not error and (not path or not digest):
            raise ValueError("successful jobs require artifact path and digest")
        now = self.clock()
        with self.database.connect() as db:
            result = db.execute(
                "UPDATE preparation_jobs SET status=?,artifact_path=?,artifact_hash=?,"
                "last_error=?,owner=NULL,lease_until=NULL,updated_at=? "
                "WHERE id=? AND status='RUNNING' AND owner=? AND lease_until>?",
                ("FAILED" if error else "SUCCEEDED", path, digest, error, now,
                 job_id, owner, now),
            )
            if result.rowcount != 1:
                raise PreparationError("worker lease lost; result was not accepted")
