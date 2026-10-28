# Local preparation and unattended cloud publication

## Agreed direction

Mac and Windows machines prepare projects locally. Expensive planning, snapshot generation,
and validation happen before upload. S3 holds immutable prepared artifacts. A small cloud
worker publishes approved stages without AI calls or arbitrary shell scripts.

Target AWS spending is below USD 100/month with headroom; AI API costs are separate and
remain to be estimated. No resources have been provisioned or priced by this milestone.
The target absence is three to four months. Coverage must be measured from real validated
stages, not generated empty commits. Uniform daily choices average two stages, so 90-120
days would average roughly 180-240 stages; the saved schedule supplies the actual coverage.

## Current implementation audit

- Implemented: local import, collection discovery, immutable revisions, bounded analysis,
  static-plan stage generation, independent final-state validation, SQLite records, and
  status bars based on recorded publication jobs.
- Added: local draft scheduling and per-project/aggregate coverage forecasts.
- Missing: automated planning, approval bound to artifact hashes, portable publication
  bundles, S3 transfer, repository provisioning, Git publication, job execution and recovery,
  cloud deployment, alerts, and an unattended rehearsal.
- Revision gap: analysis supports selected revisions, while generation and validation still
  use the original project layout. Bind all preparation steps to an explicit source revision
  before implementing export or approval.

## Draft scheduling

`schedule-preview` takes an ordered JSON queue of project IDs, names, plan hashes, and stage
counts. It does not verify those inputs against the database or approve publication.
Its output is deliberately marked DRAFT and must never be executable publication authority.

```json
{
  "projects": [
    {
      "project_id": "00000000-0000-0000-0000-000000000001",
      "name": "example",
      "plan_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "stage_count": 30
    }
  ]
}
```

```bash
git-progressor schedule-preview queue.json --start 2026-11-01 --seed departure-v1 --output schedule.json
```

The explicit start date and seed produce reproducible choices. Each Tokyo calendar day
gets one to three stages, capped by the remaining queue. Distinct times are selected from
20:00:00 through 22:59:59. Projects and stages retain their input order, including when a
day crosses a project boundary. The output is created exclusively and never overwritten.
The forecast assumes all work succeeds; it is not live remaining-work tracking.

## Publication bundle contract to implement

Use versioned JSON plus hashed snapshot files, not generated command strings. Include
project/revision/plan identities, stage inventories and hashes, reviewed commit messages,
approved repository/branch/visibility, schedule identity, and approval evidence covering
all of those values. Bundle paths must be relative and portable across operating systems.
Commit SHAs and expected remote parents are recorded during execution and recovery, not
invented during preparation. Publication dates must not misrepresent development dates.

The cloud checks bundle integrity, approval, secrets, and remote state before each push.
Upload a completion marker only after all referenced objects are present and verified.
Unprepared source uploads are stored as pending preparation, not automatically published.
New prepared projects append without changing existing approved schedule entries.

## Next milestones

1. Bind generation and validation to explicit revisions. Add hash-bound review and approval.
2. Export/import portable verified bundles and connect scheduling to approved database state.
3. Implement guarded Git publication, persistent locks, retries, and crash reconciliation.
4. Add S3 upload/download and idempotent private GitHub repository creation.
5. Cost and deploy the worker, then rehearse unattended operation and failures.

EC2 can be started ahead of the evening window and stopped after it, with state on persistent
storage. Compare this with a short-lived worker before choosing infrastructure. Shutdown,
storage, credentials, logs, and failure recovery all need explicit deployment controls.
S3 is artifact storage, not a replacement for transactional job/lock state. Do not share a
live SQLite database through S3. A single EC2 worker may use SQLite on its persistent volume;
an ephemeral or multi-worker design needs a durable shared state adapter.

Retries must preserve stage identity, never create duplicate commits, and respect the
evening window. Missed slots require an audited schedule amendment and updated forecast.
Public repositories require explicit visibility approval; private is the default.
Low-backlog and failed-job alerts, bounded log retention, and cost monitoring are required
before departure. Budget alerts are not a hard spending cap.
