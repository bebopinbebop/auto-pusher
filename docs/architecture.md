# Architecture

Git Progressor has two separately deployable conceptual subsystems. The Planner may use AI
to propose a structured plan, but it cannot access publishing credentials or Git push. The
Publisher consumes only approved, validated artifacts and never invokes AI.

```text
Completed project
      |
      v
Intake -> immutable source + manifest -> Planner port -> reviewed structured plan
      |                                      |
      |                                      v
      +----------------------------> deterministic stage snapshots
                                             |
                                             v
                              validator: final snapshot == source
                                             |
                                      human approval
                                             |
                                             v
                        publication manifest -> scheduler -> locked publisher -> Git
```

## Current milestone

Implemented: configuration, typed manifests and declarative plans, credential scanning,
`.gitignore` aware intake, verified source copying, canonical hashing, atomic full snapshots,
independent validation, SQLite stage state, CLI generation/validation, structured logging,
and inert Planner/Publisher ports.

Not implemented: provider calls, human approval, scheduling, locking, Git subprocess
execution, commits, pushes, and publisher workers.

## Core decisions

### Immutable source authority

Intake creates a new UUID directory and never overwrites it. Included files are copied as
bytes, rehashed after copying, and made read-only where supported. The manifest is the
source inventory. A future validator will independently rescan the source and compare the
last stage by path and byte digest. Operational deployments should additionally enforce
filesystem permissions or immutable object storage.

### Full stage snapshots

Stages are full directory snapshots. Each is assembled in a unique temporary sibling,
starting from the previous snapshot, then atomically renamed to its zero-padded number.
Its manifest is stored beside it. Existing stages are recomputed on regeneration and are
accepted only when they match their manifests. Content-addressed deduplication or patches
may later sit behind `SnapshotStore` without changing validation semantics.

### Independent validation

The validator never accepts the generator's hash as evidence. It walks the filesystem,
rejects symlinks and ignored metadata, reruns credential scanning, recomputes each manifest,
and compares it with persisted metadata. The final snapshot and immutable source are then
compared by path, size, individual file SHA-256, and aggregate tree hash.

```mermaid
flowchart TD
    A[Immutable source] --> B[Declarative stage plan]
    B --> C[Deterministic generator]
    C --> D[S1]
    C --> E[S2]
    C --> F[Sn]
    D --> G[Independent validator]
    E --> G
    F --> G
    A --> G
    G --> H{Exact final equality?}
    H -->|Yes| I[VALID]
    H -->|No| J[INVALID]
```

### Strict AI boundary

`Planner` accepts a source path and manifest and returns `ProjectPlan`. Pydantic rejects
unknown fields, missing fields, non-contiguous stages, unsafe paths, and conflicting file
operations. The future OpenAI adapter must request JSON matching the generated schema. AI
output is a proposal only; Python performs every filesystem operation.

### Persistence and idempotency

SQLite begins in WAL mode with foreign keys enabled. A publication job is unique per stage
and records expected parent and resulting commit SHA. Recovery will reconcile the remote
HEAD before retrying, covering a crash after push but before the local success update.

### Publisher safety

The Git port intentionally contains no force-push method. A later implementation will
verify the configured remote, branch, clean worktree, expected parent, stage validation,
and credential scan before committing. Any uncertain state fails closed.

### Locking and future HA

The `ProjectLock` protocol isolates ownership. SQLite transactional locks are appropriate
for a single host. DynamoDB conditional writes can later implement the same lease contract
for multiple EC2 workers.

## Database schema

| Table | Purpose | Important constraints |
| --- | --- | --- |
| `projects` | Source identity and workflow status | UUID primary key, source hash |
| `plans` | Immutable structured plan artifact | References project, stores plan hash |
| `stages` | Ordered reconstructable states | Unique order, hashes, paths, audit timestamps |
| `repositories` | Approved remote/branch expectations | One per project |
| `publication_jobs` | Scheduled idempotent work | One job per stage |
| `publication_history` | Append-only attempt audit | Parent/result SHA and outcome |
| `locks` | Current project lease | One owner per project |
| `schema_migrations` | Applied migration versions | Integer primary key |
