# Git Progressor

Git Progressor turns a completed software project into a reviewable sequence of logical
development stages and, in later milestones, publishes approved stages on a schedule. Its
central rule is simple: AI may suggest a plan, but deterministic Python reconstructs it,
and the final reconstructed tree must exactly match the imported project.

This repository currently implements deterministic stage generation and independent
final-state validation. It does **not** call OpenAI, commit, or push to GitHub.

## Requirements

- Python 3.11 or newer
- A local filesystem suitable for SQLite

## Install for development

```bash
python -m venv .venv
.venv/Scripts/activate       # Windows PowerShell
python -m pip install -e ".[dev]"
pytest
```

On Linux, activate with `source .venv/bin/activate`.

Copy `.env.example` to `.env` when custom paths are needed. Do not place API keys or Git
credentials in that file if it could enter version control.

## Current workflow
Stage Progression
```mermaid
flowchart TD
A[intake] -->B[analyzer] --> C[planner] --> D[stages] --> E[publisher]

```

Deterministic Progression
```mermaid
flowchart TD
    A[Completed project or project collection] --> B[Import or discover and ingest]
    B --> C[Apply exclusions, scan for secrets, and hash files]
    C --> D[Immutable source and manifest]
    D --> E[Offline deterministic analysis]
    E --> F[Versioned analysis artifact]
    F --> G[Bounded planner context for future planning]
    D --> H[Generate deterministic stage snapshots]
    P[User-supplied static plan] --> H
    H --> I[Independently validate every stage]
    D --> J{Final stage matches source?}
    I --> J
    J -->|Yes| K[Validated stages]
    J -->|No| L[Reject validation]
```

Live AI planning, execution scheduling, and publication are future milestones. Analysis does not
yet generate the static plan used for stage generation.

Import a completed project:

```bash
git-progressor import ./my-project
```

The command validates the directory, applies built-in exclusions and its `.gitignore`,
rejects symlinks and likely credentials, hashes every included file, copies it into a new
project directory, verifies the copy, writes `manifest.json`, and records the project in
SQLite. It prints the new project UUID on success.

Discover and ingest a collection of independent projects:

```bash
git-progressor ingest C:\Users\pilot\projects
```

`ingest` finds conservative project boundaries, imports new logical projects, recognizes
known revisions and moved or duplicated copies, and stores changed content as a new
immutable source revision. A failure in one candidate does not roll back other successful
imports; the command reports every outcome and exits non-zero when any candidate fails.

`sync` is intentionally not present yet. Its future meaning is reserved for actively
reconciling new revisions of known projects.

List imported projects:

```bash
git-progressor status
```

Status includes a publication bar for the latest plan once all stages are validated, for example
`[############--------]  60%  3/5 stages published`. Only publication jobs marked
`PUBLISHED` with a recorded commit SHA count toward progress. Projects without a plan
show `Awaiting plan`; unvalidated plans show `Awaiting automated validation`. No human
approval is required. Publication remains a future milestone.

Analyze the latest immutable source revision, or select an exact revision:

```bash
git-progressor analyze PROJECT_ID
git-progressor analyze PROJECT_ID --revision SOURCE_TREE_HASH
```

Analysis is deterministic, offline, and metadata-only. It records languages, declared
dependencies, evidenced frameworks/tools, tests, configuration, infrastructure,
documentation, entrypoints, lightweight modules, selected important paths, statistics,
and explicit truncation warnings. It never executes project code or includes source text.

Generate snapshots from a static, strictly validated plan:

```bash
git-progressor generate PROJECT_ID --plan ./stage-plan.json
```

The plan is persisted at `planning/plan.json`. Later idempotent runs can omit `--plan`:

```bash
git-progressor generate PROJECT_ID
git-progressor validate PROJECT_ID
```

Each operation is `add`, `modify`, or `delete`. Added and modified bytes come either from
base64 embedded in the plan or a safe relative `source_path` in the immutable source.
Generation never executes plan content. A stage is built under a unique `.tmp-*` directory,
hashed, atomically renamed, and recorded in SQLite.

Validation rescans every snapshot without trusting the generator or stored hashes. It
rejects structural gaps, unexpected stages, symlinks, ignored metadata, credentials, and
manifest mismatches. It then compares the final snapshot with the independently rescanned
source by both individual path/hash entries and aggregate tree hash. Invalid results return
a non-zero exit code and never display file contents.

The following command remains deliberately inert. It returns exit code 2 and performs no
Git operation:

```bash
git-progressor publish PROJECT_ID --dry-run
git-progressor publish PROJECT_ID
```

## Intended workflow

```bash
git-progressor import PATH
git-progressor analyze PROJECT_ID
git-progressor plan PROJECT_ID
git-progressor show-plan PROJECT_ID
git-progressor generate PROJECT_ID
git-progressor validate PROJECT_ID
git-progressor schedule PROJECT_ID
git-progressor publish PROJECT_ID --dry-run
git-progressor publish PROJECT_ID
```

Live AI planning, execution scheduling, and publication remain future milestones.

## Offline planner interface

The provider-neutral planner receives a typed request with verified revision identity,
analysis, the file inventory, and bounded UTF-8 source text (64 KiB per file, 256 KiB total).
Binary and oversized files are explicitly listed as omitted; they remain available through
declarative source references during reconstruction. Source text is intentionally separate
from the analyzer's metadata-only context. No request is sent over the network yet.

Test an existing provider response against the calculator source:

```bash
git-progressor import tests/fixtures/calculator-final
git-progressor plan PROJECT_ID --response tests/fixtures/calculator-plan.json --output data/calculator-proposal.json
```

`--revision SOURCE_HASH` selects an exact imported revision; otherwise the latest is used.
This offline adapter reads a supplied plan, not an AI-generated new plan. The service rejects
malformed responses, excessive stage counts, unsafe stages, empty changes, and a final tree
that differs from the selected source. It reconstructs stages in temporary storage without
executing their code. Temporary storage is isolation from project artifacts, not an OS sandbox.
Runtime checks and semantic accuracy of commit messages still require review.

The saved proposal includes project/revision/analysis/plan hashes and stage hashes. It is
marked `VALIDATED` under `automatic-integrity-v1`, with `human_approval_required: false`.
No human gate remains. Failed checks reject the plan; optional inspection is still available.
It never overwrites an existing output and does not yet enqueue or publish anything.
Its `plan` field contains the existing `ProjectPlan` format; the proposal
envelope itself is not input to `generate`. Existing generated snapshots are left untouched.

## Reviewing incomplete stages

Intermediate stages may be incomplete or non-runnable. Commit messages should describe
actual changes without claiming unfinished functionality works. Review the saved proposal:

```bash
git-progressor show-plan PROJECT_ID
git-progressor validate PROJECT_ID --python-syntax
```

The optional Python syntax check uses the interpreter running Git Progressor. Intermediate
syntax failures produce `REVIEW` warnings; final-stage syntax failures reject validation.
It compiles in memory without executing project code or writing bytecode. It does not
check imports, run tests, or prove that the application works. Other languages and runtime
test execution remain future work. Integrity, secret, and final-state equality checks
always block invalid output, regardless of the syntax option.

The calculator fixture demonstrates intentionally incomplete package exports in early
stages. Its plan descriptions explain those limits. You can import
`tests/fixtures/calculator-final`, generate with `tests/fixtures/calculator-plan.json`, then
use the review and validation commands above. Updated plan text changes its hash: use a
fresh import for this example rather than replacing a plan behind existing snapshots.

## Data layout

```text
data/
├── git-progressor.db
└── projects/
    └── <uuid>/
        ├── manifest.json
        ├── source/
        ├── planning/
        ├── analyses/
        │   └── <source-tree-hash>/analyzer-v1/project-analysis.json
        ├── revisions/
        │   └── <source-tree-hash>/
        │       ├── manifest.json
        │       └── source/
        ├── stages/
        │   ├── 001/
        │   ├── 001.manifest.json
        │   └── ...
        └── state/
```

The source tree is authoritative. Import never mutates the input and never overwrites an
existing project directory. See [architecture](docs/architecture.md),
[security](docs/security.md), and [project format](docs/project-format.md).

## Security assumptions

The built-in scanner catches common credential filenames, private-key headers, AWS access
key IDs, and GitHub token formats. It is deliberately a first barrier, not a guarantee.
Later publication must rescan each exact stage with a mature scanner, keep SSH keys outside
project storage, retrieve secrets through AWS Secrets Manager or SSM, redact logs, and run
under a dedicated least-privileged account.

## Tree hashing

Every file is hashed with SHA-256 over its bytes. The tree hash feeds a second SHA-256 with
each file in sorted POSIX-path order as `path`, a NUL byte, the binary file digest, and a
final NUL byte. Timestamps, permissions, ownership, and directory entries are excluded.
A one-byte content change therefore changes both the file hash and tree hash.

## Project identity and revisions

The internal UUID identifies a logical project. A deterministic `source_identity` finds
that project again without using its absolute path. Where possible it hashes the marker
type and declared project name from bounded `pyproject.toml`, `package.json`, `Cargo.toml`,
`setup.cfg`, or `go.mod` metadata. Otherwise it hashes the normalized directory name and
marker set. The separate source tree hash identifies one exact content revision.

Exact revisions are recognized after moves and across duplicate copies. Changed content at
the last known location becomes a new revision. Declared identities also survive a move and
change together. A structural identity seen at a new path with different content is
reported as a conflict because the match is ambiguous.

## Analysis limits and planner context

The analyzer uses configurable file-count, per-metadata-file, cumulative metadata-byte,
and important-file limits. All ordering is canonical, and truncation is always reported.
`analysis_hash` is SHA-256 over canonical compact JSON excluding the hash field itself.

`PlannerContextBuilder` derives a smaller typed payload solely from the saved analysis. It
contains safe classifications and paths, not excerpts or raw repository contents. A future
planner can therefore consume bounded context without direct repository access.

## Roadmap

The [OpenAI planner adapter](docs/openai-planner.md) now has bounded structured
requests and fake-client tests. `prepare-openai` connects captured model responses
to durable jobs; `planning-status` and `planning-resume` inspect and recover them.
Live API verification remains pending. Offline commands never call a model.

The [durable preparation worker](docs/preparation-worker.md) now saves offline
preparation jobs and their validated stage snapshots. Use `prepare PROJECT_ID
--response PLAN.json`, `preparation-status JOB_ID`, and `prepare-resume JOB_ID`
to run, inspect, and recover work. This is single-host processing; it makes no AI
requests or Git pushes and is not yet connected to AWS or the publication queue.

The [cloud roadmap](docs/cloud-roadmap.md) describes local preparation, S3 handoff,
unattended publication, and the implementation gaps. A local `schedule-preview` command
now saves reproducible draft evening schedules and coverage forecasts; it does not approve
or publish work. See the roadmap for its queue format and command example.

1. Extract artifact and state-store ports for local and future AWS adapters.
2. Bind automatic validation evidence to immutable artifacts and connect validated plans to jobs.
3. Integrate the Responses API with strict structured output and redacted inputs.
4. Add publication manifests, scheduling, locking, and guarded Git publication.

---

## Milestone addendum — November 1, 2026

This section is appended to preserve the earlier README specifications for later
editing. It describes the current implementation and supersedes older statements
above that the application cannot call OpenAI or that every planning component is
still a placeholder. Earlier examples remain useful, but the commands below
describe the new durable preparation workflow.

### What the project accomplishes today

Git Progressor accepts a finished project as the source of truth. It can take a
supplied development plan, or explicitly request one through OpenAI, reconstruct
its stages, and check that the final stage contains the original included files
with identical bytes. Intermediate stages may be unfinished. Commit messages
should explain the actual changes without claiming that unfinished features work.

The planner proposes changes; ordinary Python applies and verifies them. There is
no human approval gate. Automated validation is mandatory, while inspection is
optional. Passing integrity validation does not prove that intermediate code runs
or that every explanation is semantically accurate.

| Component | Current state | Important boundary |
| --- | --- | --- |
| Intake and revisions | Implemented locally | Exclusions, credential heuristics, immutable source copies and hashes |
| Deterministic analysis | Implemented | Bounded metadata analysis; no project execution |
| Offline planning | Implemented | Reads a supplied response rather than inventing one |
| OpenAI adapter | Implemented and tested with simulated responses | Actual generation has not yet succeeded in the live trial |
| Durable preparation | Implemented with SQLite and local files | One host; not a distributed AWS worker yet |
| Stage validation | Implemented | Final-source equality and security checks block invalid plans |
| Model request recovery | Implemented | Captured responses are reused; uncertain requests are not automatically repeated |
| Draft scheduling | Implemented locally | A forecast, not an executable publishing queue |
| Git publication | Not implemented | `publish` remains inert; no application-driven commits or pushes |
| AWS infrastructure | Foundation code and design documentation | No resources deployed during this session |
| Dashboard and cost reporting | Planned | No running website or billing collector yet |

### Current local processing flow

```mermaid
flowchart TD
    finished["Finished project"] --> intake["Import, exclusions, secret scan, hashes"]
    intake --> source["Immutable source revision and manifest"]
    source --> context["Analysis and bounded source context"]
    context --> choice{"Planning input"}
    choice -->|"Offline"| supplied["Supplied ProjectPlan JSON"]
    choice -->|"Explicit paid request"| adapter["OpenAI Responses adapter"]
    adapter --> ledger["Capture response, token usage and provenance"]
    supplied --> job["Durable preparation job"]
    ledger --> job
    source --> job
    job --> stages["Deterministic stage snapshots"]
    stages --> validation{"Integrity and final-source equality"}
    validation -->|"Pass"| saved["Retained validated artifacts"]
    validation -->|"Fail"| failure["Recorded failure; no publication"]
    saved -.-> future["Future verified publishing queue"]
```

The API receives bounded context and selected source excerpts, not unrestricted
filesystem access. Binary and omitted files remain addressable through source
references. Generated file changes are declarative add/modify/delete operations;
the model is not given shell execution tools.

### What was added in this session

1. A persistent preparation job store with pinned source revisions, captured
   offline response bytes, attempt counts, and worker leases.
2. Retained source manifests, proposals, stage snapshots, and an aggregate artifact
   digest, rather than discarding all generated stages after proposal validation.
3. A bounded Responses API adapter with strict structured output, local schema
   validation, input/output limits, explicit model selection, and no SDK retries.
4. A model-request ledger that saves responses before deterministic preparation,
   records reported token usage, and links requests to preparation jobs.
5. Recovery commands that reuse saved work without contacting the model again.
6. An explicit failed-request retry command, capped at three total API attempts,
   with historical failure and usage evidence retained.
7. Sanitized provider error categories for authentication, permissions, model lookup,
   bad requests, rate/quota limits, server failures, connection failures and timeouts.
8. Offline tests covering replay, corrupt artifacts, concurrent claims, interrupted
   work, response reuse, malformed output, and bounded retries.

The complete suite passed **101 tests** before this documentation addendum, and
lint passed for changed Python files. These results establish the tested local
behavior; they are not evidence of a successful production cloud deployment.

### OpenAI request lifecycle and retry boundaries

```mermaid
stateDiagram-v2
    [*] --> PENDING: Persist request identity
    PENDING --> STARTED: Atomically claim one API attempt
    STARTED --> CAPTURED: Save response and reported usage
    STARTED --> FAILED: Record a handled failure
    FAILED --> PENDING: Explicit planning-retry below attempt limit
    CAPTURED --> Preparation: Reuse saved response
    Preparation --> Validated: Checks pass
    Preparation --> PreparationFailed: Checks fail
    PreparationFailed --> Preparation: Explicit deterministic retry
```

A process that stops during an API attempt can leave a request in STARTED. That
state is deliberately not auto-reset: the provider may have received and charged
for the call even though no response was saved locally. Explicit API retry also
refuses STARTED requests. Reconciliation for those uncertain outcomes is future work.

CAPTURED means a response is saved, not that its stages have passed validation.
Preparation can fail after capture; its retry reuses the saved response. Repeating
an identical successful request verifies existing artifacts rather than generating
another response. Changing the project, context, model or policy can create a new
request identity and therefore another potentially billable call.

```mermaid
sequenceDiagram
    participant cli as CLI
    participant state as SQLite ledger
    participant ai as OpenAI API
    participant worker as Preparation worker
    participant disk as Local artifacts
    cli->>state: Find or persist pinned request
    alt Response already captured
        state-->>cli: Saved response and preparation link
    else New request
        cli->>state: Claim PENDING request as STARTED
        cli->>ai: Bounded structured planning request
        ai-->>cli: Response or failure
        cli->>state: Persist capture or sanitized failure
    end
    cli->>worker: Prepare captured response
    worker->>disk: Build isolated attempt snapshots
    worker->>disk: Verify hashes and final-source equality
    worker->>state: Record validated artifact pointer if lease is current
```

### Preparation leases and files

Preparation jobs move through PENDING, RUNNING, SUCCEEDED, or FAILED. An atomic
SQLite update gives one worker a 15-minute lease. Only the current, unexpired
owner can accept a result. An expired attempt may be reclaimed, with at most
three attempts. There is no heartbeat or automatic polling loop yet.

Each attempt has a separate output directory. A crash before the success record
leaves an unreferenced directory; a retry rebuilds elsewhere. A crash after the
record commits is handled by checking and reusing the recorded output. Missing
or changed completed artifacts are rejected, not silently repaired.

```text
data/
├── git-progressor.db
├── projects/<project-id>/
│   ├── source/
│   ├── manifest.json
│   └── revisions/...
└── preparations/<job-id>/<attempt-owner>/
    ├── response.json
    ├── proposal.json
    ├── manifest.json
    ├── source/
    └── stages/
        ├── 001/
        ├── 001.manifest.json
        └── ...
```

The SQLite artifact pointer marks accepted output. Filesystem storage and the
database are trusted local boundaries; the hashes are not signatures. Failed and
abandoned attempt directories are retained. Cleanup policies and storage quotas
remain future work. These jobs do not yet populate the legacy publication tables
or turn the existing publication progress bar into a live publishing report.

| Migration | Added state |
| --- | --- |
| 5 | `preparation_jobs`: source/response identity, lease, attempts, artifacts and failures |
| 6 | `planning_requests`: context/model/policy identity, response, usage and linked job |
| 7 | Model attempt counts and `planning_retry_history` for explicitly retried failures |

### WSL setup and commands

WSL is the current development and test environment. A Linux virtual environment
must be created separately from a Windows virtual environment. Existing users can
activate their `.venv-wsl`; new users can create it first:

```bash
python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install -e '.[dev,openai]'
```

Load an API key only in the terminal that will execute live planning. The following
prompt hides the pasted value and avoids entering it directly into shell history:

```bash
read -rsp "OpenAI API key (hidden): " OPENAI_API_KEY
printf '\n'
export OPENAI_API_KEY
```

This environment variable is local to that terminal and its child processes. It
is not automatically available to a separate IDE or agent terminal. The SDK
factory reads it from the process environment; placing it only in `.env` does not
make it available to that factory. Never paste keys into issues, screenshots, chat,
Git commits, or source files.

| Command | Purpose | Can invoke a paid model request? |
| --- | --- | --- |
| `prepare PROJECT_ID --response PLAN.json` | Capture an offline response and retain validated stages | No |
| `preparation-status JOB_ID` | Inspect preparation status and attempts | No |
| `prepare-resume JOB_ID` | Resume pending/expired work or verify completed artifacts | No |
| `prepare-resume JOB_ID --retry` | Retry failed deterministic preparation | No |
| `prepare-openai PROJECT_ID --model MODEL` | Request a plan and connect capture to preparation | Yes, for a new request |
| `planning-status REQUEST_ID` | Inspect request status, usage and preparation link | No |
| `planning-resume REQUEST_ID` | Prepare an already captured response | No |
| `planning-resume REQUEST_ID --retry` | Retry failed preparation using captured data | No |
| `planning-retry REQUEST_ID` | Explicitly retry a FAILED API request | Yes, up to three total attempts |

Prefix each command with `git-progressor`. Import a project once and retain its
ID. Do not re-import simply to bypass a failed request; a new project identity can
trigger a separate paid call. For the calculator fixture:

```bash
git-progressor import tests/fixtures/calculator-final
# Substitute the printed project ID below.
git-progressor prepare PROJECT_ID --response tests/fixtures/calculator-plan.json
# Optional live test: substitute a supported, accessible model explicitly.
git-progressor prepare-openai PROJECT_ID --model MODEL
```

The adapter defaults to 8,192 output tokens and a 120-second timeout. Output tokens
are not commits or remaining account credits. Input tokens also incur charges;
byte/token limits are not a dollar spending cap. No automatic paid fallback exists.
See [OpenAI setup and recovery](docs/openai-planner.md) for configuration limits.

### Live trial result and present blocker

During the November 1 session, authentication and model metadata lookup succeeded
from the user's WSL terminal. The subsequent recorded planning retry returned a
rate-or-quota error. That category can indicate a rate limit, unavailable quota,
or billing/usage restrictions; it does not identify the exact cause by itself.
No successful live-generated calculator plan has been verified yet.

Two attempts were used for that trial request. No token usage was returned in its
saved record, which does not establish that no charge occurred. Before another
attempt, inspect API billing and limits and preserve the existing request identity.
The earlier attempt retained only a generic error; improved diagnostics cannot
retroactively recover discarded provider detail.

Repository commits made during development are separate from the application's
future Git publisher. Pushing this tool's source to GitHub does not mean scheduled
publication of user projects has been implemented.

### Planned AWS architecture — not deployed

The intended operational workflow is cloud-first: Windows/WSL and Mac computers
upload finished projects, and cloud workers prepare them while those computers
are offline. Local processing is currently how the logic is developed and tested,
not a requirement that every future project be preprocessed on a personal device.

```mermaid
flowchart TD
    devices["Windows or Mac uploader"] --> bucket["Private S3 project data"]
    bucket --> marker["Completion marker notification"]
    marker --> intakeQueue["SQS intake queue and dead-letter queue"]
    intakeQueue --> dispatch["Dispatcher and Step Functions"]
    dispatch --> planner["On-demand Fargate planning worker"]
    images["ECR pinned application image"] --> planner
    secrets["Secrets Manager and scoped IAM roles"] --> planner
    planner --> openai["OpenAI Responses API"]
    planner --> state["DynamoDB jobs, leases and usage reservations"]
    planner --> artifacts["S3 validated stages and reports"]
    schedule["EventBridge publication schedule"] --> publishQueue["Publication queue"]
    publishQueue --> publisher["Deterministic publisher: Lambda candidate"]
    artifacts --> publisher
    state --> publisher
    secrets --> publisher
    publisher --> github["GitHub repositories"]
    publisher -.-> fallback["Fargate fallback for larger publication jobs"]
```

Every AWS component in this diagram is a deployment target, not a running service
provided by the current application. Terraform currently contains a private S3
foundation and legacy EC2 role/profile; the broader serverless design is documented
in [the Terraform architecture plan](deployment/terraform/ARCHITECTURE.md).

- S3 stores uploaded source, pinned revisions, validated snapshots and reports.
  Prefixes organize data; IAM and bucket policies enforce access boundaries.
- ECR stores released application images. Uploaded project source must never be
  treated as the worker application itself or as a shell script to execute.
- SQS absorbs upload events and retries; duplicate events require stable identity
  and conditional job transitions.
- Fargate is planned for longer preparation work. Short publication tasks may fit
  Lambda; runtime, disk and repository-size measurements must validate that choice.
- DynamoDB replaces local SQLite for distributed jobs and leases. A live SQLite
  database must not be synchronized between workers through S3.
- EventBridge supplies schedule triggers. A trigger does not override stage order,
  validation, lease ownership or remote Git checks.
- Separate worker roles and managed secrets replace dependence on personal terminal
  credentials. Terraform state requires its own restricted backend design.

No always-on EC2 instance is required by the current target design. EC2 remains a
possible alternative after workload and cost measurement. Serverless is not assumed
to be universally cheaper; storage, requests, logs, networking and model calls must
all be included in deployment estimates.

### Future publication and coverage reporting

The local schedule preview chooses one to three meaningful stages per Tokyo day,
with distinct times from 8 PM through just before 11 PM. It preserves project and
stage order, using a saved seed for reproducibility. Its output is DRAFT and is not
authorization for a publisher to execute arbitrary input.

The future publisher should consume verified stage data, not AI-generated commands.
It will check the repository, remote, branch, clean worktree, expected parent,
credentials and stage integrity; then commit, push without force, and record the
result. Crash recovery must reconcile a remote push before making another commit.
Creating new repositories and authorizing a dedicated GitHub identity are still
implementation work.

Coverage reporting should show stages remaining, per-project completion dates and
aggregate backlog duration from the saved schedule. Failures and exhausted backlog
must be visible. Neither a schedule nor this application can guarantee a GitHub
contribution square every day.

### Planned dashboard and cost visibility

```mermaid
flowchart LR
    browser["Authenticated viewer"] --> frontend["CloudFront and static S3 frontend"]
    frontend --> api["Authenticated read-only API"]
    api --> statusStore["DynamoDB status and coverage"]
    api --> costCache["Cached cost summaries"]
    collector["Scheduled billing collector"] --> costCache
    billing["AWS Cost Explorer"] --> collector
    modelUsage["Model usage ledger and versioned rates"] --> costCache
    budgets["AWS Budgets alerts"] --> alerts["Configured notification channel"]
```

This dashboard is planned, not implemented. It should display completed work, next
stages, failures, backlog coverage, AWS spending and separately identified model
usage estimates. Billing data has latency and must show its freshness. AWS totals
must not be presented as total AWS-plus-OpenAI spending. Budget alerts are not an
instantaneous hard cutoff. The working budget target remains USD 100 per month,
with deployment costs and whether AI is included to be finalized before launch.

### Next implementation milestones

1. Resolve the live API rate/quota blocker and validate one real calculator plan.
2. Inspect actual stage changes and messages, then test a representative real project.
3. Add durable spending reservations, uncertain-call reconciliation, resource limits,
   artifact cleanup and renewable worker leases.
4. Define portable artifact/state adapters and implement private S3 upload plus
   cloud preparation deployment from pinned releases.
5. Implement GitHub repository provisioning and deterministic publication, including
   remote divergence checks and recovery after a successful push.
6. Connect validated database state to saved schedules and coverage forecasts.
7. Build the authenticated dashboard, alerts and cost reporting, then rehearse
   unattended operation and failures before relying on it while away.

Related references: [architecture](docs/architecture.md),
[preparation worker](docs/preparation-worker.md),
[OpenAI planner](docs/openai-planner.md),
[cloud roadmap](docs/cloud-roadmap.md), and
[Terraform design](deployment/terraform/ARCHITECTURE.md).

### November 3 update: planning starts from an empty tree

The latest calculator API attempt returned a captured response and token usage,
so the earlier rate-or-quota error no longer describes that attempt. Its plan
was rejected during preparation: it tried to modify files before adding them.
Successful API generation does not mean a valid development plan was produced.

Planner instructions now explicitly describe an empty initial directory and
require each stage to build on the preceding stage. The supplied finished
source remains a read-only reference. Before creating proposal artifacts,
the planning service simulates the file inventory and rejects additions of
existing files, modifications/deletions of missing files, unknown source
references, empty operation lists, and a final inventory different from source.
Snapshot replay, secret scanning, no-change detection and byte-for-byte final
validation remain independent checks. Intermediate stages may still be incomplete.

The request policy is now `responses-plan-v2`. A newly requested plan uses the
updated instructions and a distinct request identity; historical responses and
attempt counters are preserved. This does not automatically retry or repair a
captured invalid plan. A new live planning request is billable and remains an
explicit CLI action. AWS deployment and scheduled GitHub publication remain
future work.

### Live feature-progression experiment

A subsequent live calculator plan successfully completed preparation with three
stages: core arithmetic and packaging, exports and documentation, then tests.
The retained final snapshot matched the imported source exactly. This demonstrates
the live preparation path at calculator scale, not production readiness or a
guarantee that the proposed development sequence is sufficiently detailed.

Policy `responses-plan-v3` asks for feature-level changes inside substantive text
modules, using intermediate contents before restoring the exact final bytes. It
discourages filler changes and does not impose an arbitrary number of commits.
The first live v3 experiment failed response validation before stage generation;
its recorded usage was 1,647 input tokens and 1,720 output tokens. The old generic
error did not retain enough detail to determine the cause. No automatic retry was
made, and the earlier successful three-stage result remains intact.

New response failures now record allowlisted categories for incomplete responses,
refusals, empty/oversized output, and schema violations. Raw provider messages and
model output are not included in those error diagnostics. These categories help
diagnose future attempts; they cannot recover details lost by older attempts.
Feature-level planning quality still needs a successful live trial before moving
on to unattended publication.

### AWS handoff preparation and final-source binding

The controlled retry captured a feature-level calculator plan. Its generated final
inline bytes differed from the source. Preparation now applies an explicit audited
policy: each final file's last write is bound to its authoritative source bytes,
while earlier intermediate implementations remain intact. The original response,
original plan hash, normalized plan hash and adjusted operations are retained in
local preparation evidence. This is normalization by Python, not proof that the
model generated exact final bytes unaided. Existing integrity checks still apply.

Reprocessing that captured response offline succeeded without another API call.
The three-stage feature plan was exported to a portable ZIP and independently
reconstructed. `bundle-export` and `bundle-verify` now support this handoff without
shipping the local database or requiring a model call on the receiving machine.
The expected bundle checksum must be supplied through trusted deployment state.

A non-root Dockerfile and allowlisted build context are present. Terraform now
includes an immutable-tag ECR repository alongside its existing storage foundation.
Terraform validation, lint and all 108 tests passed at this milestone. The container
build remains unverified: Docker Desktop failed while starting its inference-manager
component on the development machine. No Docker reset was performed.

See [AWS handoff readiness](docs/aws-readiness.md) for commands, limits and deploy
order. No AWS resources or GitHub publication jobs have been deployed. Automatic raw
upload processing, distributed state, Git publication, daily contribution monitoring
and the dashboard still require implementation and unattended testing.

### November 4 update: container verification passed

Docker Desktop's Linux engine is now available. The worker image built successfully,
and the live calculator bundle reconstructed all three stages inside the container
with networking disabled, a read-only root filesystem, dropped capabilities and no
API key. The runtime uses the configured non-root user. No Docker reset was needed.

`deployment/smoke_container.py` makes these release checks repeatable. Supply the
bundle and its trusted SHA-256. The Dockerfile now pins the tested Python base image
digest; Python dependency locking remains a production-readiness task. Terraform's
foundation documentation now includes the ECR repository added in the prior milestone.

This clears the earlier container build blocker. AWS credentials, remote state setup,
infrastructure review and deployment remain ahead, along with distributed processing
and actual Git publication. No AWS resources were created by these checks.

### November 4 update: US East 1 foundation plan

The AWS foundation now targets `us-east-1`, as requested; the publication timezone
remains Tokyo. The unused legacy EC2 role is opt-in. A real Terraform plan against
the authenticated account reports seven additions, zero changes and zero deletions
for private S3 storage and ECR. The plan and account-specific values remain local
and Git-ignored. Nothing has been applied; remote state setup and a regenerated
deployment plan are still needed before managing infrastructure from both computers.

## 🎯 What a successful four-month run looks like

Imagine uploading a finished project from your MacBook, adding a second one from Windows, and putting both laptops away. Git Progressor should prepare the projects in AWS and publish their stages to GitHub in order. Someone reading the commits should be able to tell what each stage accomplished. At the last commit, the tracked files must match the imported project byte for byte, after the configured exclusions.

**The daily target is at least one qualifying GitHub contribution.** The scheduler should reserve one meaningful stage for each evening it promises to cover before assigning extra pushes. The dashboard should distinguish three observations for a day: a stage was scheduled, GitHub accepted its commit, and the contribution appeared on the profile. Each answers a different question when a day looks gray.

### 📦 Follow one project from upload to publication

This diagram shows the **target cloud workflow**. The calculator has exercised the planning, validation and bundle steps locally and in Docker. Cloud intake and scheduled Git publication are upcoming milestones.

```mermaid
flowchart TD
    upload["Upload a finished project to private S3"] --> plan["AI proposes stages and commit messages"]
    plan --> replay["Start empty and apply each stage in order"]
    replay --> check{"Safe stages and exact final files?"}
    check -->|Pass| bundle["Save the verified bundle and its checksum"]
    check -->|Fail| hold["Record the failure and isolate this project"]
    bundle --> queue["Append stages after existing scheduled work"]
    queue --> due["Publish the next due stage to its GitHub repository"]
    due --> track["Track the commit, daily contribution and remaining days"]
    classDef ready fill:#dcfce7,stroke:#15803d,color:#14532d
    classDef stopped fill:#fff1f2,stroke:#be123c,color:#881337
    class bundle ready
    class hold stopped
```

For the calculator, one useful intermediate file implements addition and subtraction. A later version adds multiplication and guarded division. Both stages touch the same module, so a reader sees how the behavior grew. The planner supplies the proposal. Python keeps the original response, records any adjustment that binds a final write to source bytes, and verifies the resulting files. Once a bundle passes, the intended publisher has everything it needs to execute the saved stages without another model call.

### 🌙 Read the schedule as days of coverage

Suppose six verified stages are ready across a calculator and a notes app. The table is an **illustrative saved schedule**. Each time represents one commit and push. The daily draw is one to three stages across the whole queue, between 8 and 11 p.m. Tokyo time. AWS resources are planned for US East 1.

| Evening | Tokyo time and planned change | Stages left after success |
| --- | --- | ---: |
| Monday | 20:24 calculator addition and subtraction · 21:52 multiplication and guarded division | 4 |
| Tuesday | 20:48 calculator tests and README · 22:16 create and save notes in the next project | 2 |
| Wednesday | 21:11 search notes by title | 1 |
| Thursday | 20:37 cover empty search results with tests | 0 |

Tuesday finishes one repository and starts the next. Six stages cover **four evenings** in this example. The calculator's last scheduled day and the notes app's first scheduled day overlap, so adding their individual durations would overstate the backlog. Thursday is the last covered evening. A new upload extends that forecast once its stages pass validation and receive slots.

### 🔁 Recover after GitHub accepts a push

The **planned publisher** must handle a specific failure: GitHub accepts a commit, then the worker stops before saving success. Its replacement needs enough information to recognize the commit already on GitHub.

```mermaid
sequenceDiagram
    participant worker as Publisher
    participant state as Job store
    participant remote as GitHub
    worker->>state: Claim stage and save expected parent and prepared commit ID
    worker->>remote: Push the prepared commit
    remote-->>worker: Branch updated
    worker--xstate: Worker stops before recording success
    participant recovery as Recovery worker
    recovery->>state: Claim expired job and read saved commit ID
    recovery->>remote: Fetch branch and check the expected commit
    remote-->>recovery: Expected commit is present on the target branch
    recovery->>state: Mark stage published and record the commit ID
```

That sequence has one published commit. If recovery finds unexpected branch history, it should flag the job for investigation. The next scheduled stage depends on knowing which commit actually landed.

### 🧭 Milestones to work from

| Milestone | Evidence of completion |
| --- | --- |
| ✅ Local preparation and portable bundles | The Docker smoke test rebuilt all three live calculator stages offline and verified the final source. |
| 📍 Shared Terraform state | Both computers use the same protected backend and state key. A fresh plan shows the intended private S3 bucket and ECR repository. [Resume checklist](docs/aws-readiness.md#resume-checklist-shared-terraform-state) |
| ⬜ Cloud intake and planning | Upload a sample, disconnect the laptop, then retrieve a validated bundle from AWS. Deliver the same upload event twice and confirm it produces one job. |
| ⬜ GitHub publication | Publish a stage to a test repository. Interrupt after the push and prove recovery records the original commit. Test opening the next project's repository and continuing in order. |
| ⬜ Daily coverage and operations | A rehearsal shows qualifying contributions, warns before the backlog runs out, and reports per-project finish dates, overall coverage, failures and spending against the monthly budget. |

The operating target is three to four months of unattended publication within the planned $100 monthly budget. The departure check is a saved schedule with enough **distinct covered days**, plus a rehearsal that exercises a failed upload, an interrupted push and a nearly empty queue.
