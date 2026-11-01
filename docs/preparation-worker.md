# Durable preparation worker

This milestone executes one offline preparation job on one host. It retains the
validated proposal, authoritative source copy, source manifest, and every stage
snapshot. It does not call a live model, execute project code, schedule publication,
push Git commits, or create cloud resources.

## Commands

After importing a project, supply its ID and a recorded ProjectPlan JSON response:

```bash
git-progressor prepare PROJECT_ID --response tests/fixtures/calculator-plan.json
git-progressor preparation-status JOB_ID
git-progressor prepare-resume JOB_ID
git-progressor prepare-resume JOB_ID --retry
```

Use the calculator response only with the calculator fixture source. `prepare`
prints the job ID before execution. `--revision HASH` pins an explicitly selected
source revision; otherwise the latest revision is resolved once at enqueue time.
The response is captured in SQLite, so editing the input file later cannot change
an existing job. The same project, revision, and response bytes reuse the same job.
A different response creates a new job.

## State and recovery

Migration 5 adds `preparation_jobs`, independently of the future publication queue.
States are PENDING, RUNNING, SUCCEEDED, and FAILED. Records include the source hash,
response and its hash, attempt count, lease owner and expiry, artifact path and hash,
timestamps, and a sanitized error class. Job status never prints the stored response.

An atomic SQLite update claims a job for 15 minutes. Only its current unexpired
owner can record a result. A second worker cannot claim an active job; after lease
expiry a replacement can claim it. Attempts are limited to three. Ordinary failures
require `--retry`; interrupted RUNNING jobs can resume after lease expiry. This CLI
does not automatically poll or retry jobs. There is no lease heartbeat yet: work
exceeding 15 minutes cannot complete successfully and needs recovery.

Each attempt writes to `data/preparations/JOB_ID/OWNER_ID/`. Completion becomes
visible through the SQLite artifact pointer only after generation and validation.
A crash before that transaction commits leaves an unreferenced attempt directory;
recovery rebuilds in a fresh directory. A crash after it commits is handled by
verifying and returning the existing result. Repeated execution checks the full
artifact digest and refuses missing or changed output. It does not silently repair
completed output or claim that it was published.

Unreferenced directories are retained for diagnosis; automatic cleanup and storage
quotas remain future work. Keep the data directory private: source, recorded model
responses, and failed attempts may contain sensitive project material. Credential
scanning is heuristic, not a guarantee. Database and filesystem access are trusted
local boundaries; hashes detect changes but are not cryptographic signatures.

## Cloud handoff

The worker orchestrates existing planning, deterministic generation, and validation.
Its job store is separate from that orchestration. SQLite and local paths are for
the single-host implementation; multi-host AWS execution still needs a durable
object-store adapter, a distributed conditional job store, queue integration,
renewable leases, resource limits, and a versioned artifact format. Successful
preparation does not yet populate the legacy stage/publication tables or their
publication progress display. The [OpenAI handoff](openai-planner.md) can now
capture a model response and enqueue it here; real API verification, cloud
integration, and publisher recovery remain subsequent milestones.
