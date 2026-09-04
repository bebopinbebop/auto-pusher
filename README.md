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

Import a completed project:

```bash
git-progressor import ./my-project
```

The command validates the directory, applies built-in exclusions and its `.gitignore`,
rejects symlinks and likely credentials, hashes every included file, copies it into a new
project directory, verifies the copy, writes `manifest.json`, and records the project in
SQLite. It prints the new project UUID on success.

List imported projects:

```bash
git-progressor status
```

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

The following commands remain deliberately inert. They return exit code 2 and perform no
provider or Git operation:

```bash
git-progressor analyze PROJECT_ID
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
git-progressor approve PROJECT_ID
git-progressor schedule PROJECT_ID
git-progressor publish PROJECT_ID --dry-run
git-progressor publish PROJECT_ID
```

`plan`, `show-plan`, approval, scheduling, and publication remain future milestones.

## Data layout

```text
data/
├── git-progressor.db
└── projects/
    └── <uuid>/
        ├── manifest.json
        ├── source/
        ├── planning/
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

## Roadmap

1. Add explicit plan review and approval commands around the static plan artifact.
2. Integrate the Responses API with strict structured output and redacted inputs.
3. Add publication manifests, scheduler, SQLite locking, and dry-run diff reporting.
4. Implement guarded Git publication and crash-safe remote reconciliation.
5. Harden deployment, secret scanning, and later add DynamoDB lock/state adapters.
