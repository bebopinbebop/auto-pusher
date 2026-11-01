"""Capture one provider response durably before executing deterministic preparation.

STARTED requests are never automatically reissued: a crash or timeout could have
incurred a charge even when no response was saved. Recovery reuses CAPTURED data.
"""
import hashlib
import json
from uuid import UUID, uuid4

from git_progressor.exceptions import PlannerRequestError
from git_progressor.planner.service import MAX_RESPONSE_BYTES
from git_progressor.security import CredentialScanner
from git_progressor.storage.preparation import PreparationError

POLICY_VERSION = "responses-plan-v1"


class LivePlanningService:
    def __init__(self, worker):
        self.worker = worker
        self.database = worker.jobs.database
        self.clock = worker.jobs.clock

    def request(self, project_id, *, model, max_output_tokens, revision=None):
        request, manifest, _ = self.worker.planning.prepare(project_id, revision)
        request_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        now = self.clock()
        key = (str(project_id), manifest.source_hash, request_hash, model,
               max_output_tokens, POLICY_VERSION)
        with self.database.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO planning_requests "
                "(id,project_id,source_hash,request_hash,model,max_output_tokens,policy_version,"
                "status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'PENDING',?,?)",
                (str(uuid4()), *key, now, now),
            )
            row = db.execute(
                "SELECT * FROM planning_requests WHERE project_id=? AND source_hash=? "
                "AND request_hash=? AND model=? AND max_output_tokens=? AND policy_version=?", key,
            ).fetchone()
        return dict(row), request

    def get(self, request_id):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM planning_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise PreparationError("unknown planning request")
        return dict(row)

    def run(self, project_id, *, model, max_output_tokens, provider_factory,
            revision=None, retry_preparation=False):
        if not model or not model.strip() or not 1 <= max_output_tokens <= 32768:
            raise PreparationError("explicit model and bounded token limit required")
        record, request = self.request(project_id, model=model,
                                       max_output_tokens=max_output_tokens, revision=revision)
        if record["status"] == "PENDING":
            # Missing credentials/dependencies must not consume the one request attempt.
            provider = provider_factory()
            if provider.model != model or provider.max_output_tokens != max_output_tokens:
                raise PreparationError("provider configuration differs from recorded request")
            with self.database.connect() as db:
                claimed = db.execute(
                    "UPDATE planning_requests SET status='STARTED',attempts=attempts+1,"
                    "last_error=NULL,usage_json=NULL,updated_at=? "
                    "WHERE id=? AND status='PENDING' AND attempts<3", (self.clock(), record["id"]),
                ).rowcount
            if claimed != 1:
                raise PreparationError("planning request already claimed; no API call made")
            try:
                raw = provider.create_plan(request)
                if not isinstance(raw, str) or len(raw.encode()) > MAX_RESPONSE_BYTES:
                    raise PreparationError("response exceeds byte limit")
                if any(p.search(raw.encode()) for p in CredentialScanner.PATTERNS.values()):
                    raise PreparationError("suspected credentials in response")
                digest = hashlib.sha256(raw.encode()).hexdigest()
                with self.database.connect() as db:
                    db.execute(
                        "UPDATE planning_requests SET status='CAPTURED',response=?,"
                        "response_hash=?,usage_json=?,updated_at=? WHERE id=? AND status='STARTED'",
                        (raw, digest, self._usage(provider), self.clock(), record["id"]),
                    )
            except Exception as exc:
                error = (
                    f"PlannerRequestError:{exc.category}"
                    if isinstance(exc, PlannerRequestError) else type(exc).__name__
                )
                with self.database.connect() as db:
                    db.execute(
                        "UPDATE planning_requests SET status='FAILED',last_error=?,usage_json=?,"
                        "updated_at=? WHERE id=? AND status='STARTED'",
                        (error, self._usage(provider), self.clock(), record["id"]),
                    )
                raise PreparationError(
                    f"planning failed ({error}); request will not be automatically repeated"
                ) from None
        return self.resume(record["id"], retry_preparation=retry_preparation)

    def retry_failed(self, request_id, *, provider_factory):
        """Explicitly authorize one additional call, retaining prior failure evidence."""
        record = self.get(request_id)
        if record["status"] != "FAILED" or record["attempts"] >= 3:
            raise PreparationError("only FAILED requests below three attempts can be retried")
        if record["policy_version"] != POLICY_VERSION:
            raise PreparationError("planning policy changed; old request cannot be retried")
        project_id = UUID(record["project_id"])
        request, _, _ = self.worker.planning.prepare(project_id, record["source_hash"])
        if hashlib.sha256(request.model_dump_json().encode()).hexdigest() != record["request_hash"]:
            raise PreparationError("planning context changed; old request cannot be retried")
        provider = provider_factory()
        if (provider.model != record["model"]
                or provider.max_output_tokens != record["max_output_tokens"]):
            raise PreparationError("retry must preserve original model and token cap")
        with self.database.connect() as db:
            changed = db.execute(
                "UPDATE planning_requests SET status='PENDING',updated_at=? "
                "WHERE id=? AND status='FAILED' AND attempts=? AND attempts<3",
                (self.clock(), request_id, record["attempts"]),
            ).rowcount
            if changed != 1:
                raise PreparationError("request changed concurrently; no retry authorized")
            db.execute(
                "INSERT INTO planning_retry_history "
                "(request_id,attempt,status,last_error,usage_json,archived_at) "
                "VALUES (?,?,?,?,?,?)",
                (request_id, record["attempts"], record["status"], record["last_error"],
                 record["usage_json"], self.clock()),
            )
        return self.run(project_id, model=record["model"],
                        max_output_tokens=record["max_output_tokens"],
                        revision=record["source_hash"], provider_factory=lambda: provider)

    @staticmethod
    def _usage(provider):
        usage = getattr(provider, "last_usage", None) or {}
        # Persist counts only, never arbitrary provider metadata or error messages.
        return json.dumps({name: value for name in
                           ("input_tokens", "output_tokens", "total_tokens")
                           if isinstance((value := usage.get(name)), int) and value >= 0})

    def resume(self, request_id, *, retry_preparation=False):
        record = self.get(request_id)
        if record["status"] != "CAPTURED":
            raise PreparationError(
                f"planning request is {record['status']}; no saved response to resume"
            )
        raw = record["response"]
        if hashlib.sha256(raw.encode()).hexdigest() != record["response_hash"]:
            raise PreparationError("captured response integrity mismatch")
        job_id = self.worker.jobs.enqueue(record["project_id"], record["source_hash"], raw)
        with self.database.connect() as db:
            db.execute("UPDATE planning_requests SET preparation_job_id=?,updated_at=? WHERE id=?",
                       (job_id, self.clock(), request_id))
        return self.worker.run(job_id, retry=retry_preparation)
