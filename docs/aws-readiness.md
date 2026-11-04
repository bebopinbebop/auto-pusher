# AWS handoff readiness

The next deployable milestone is artifact storage and application release storage,
not the full unattended publisher. No AWS resources are deployed by these changes.

## Preparation and portable artifacts

The live calculator now has a captured model response. Final-source binding records
the original plan hash, normalized plan hash, and each changed last-write operation
in `proposal.json`. Earlier intermediate implementations are retained. Final writes
use authoritative source bytes; this may change the behavior of the last write,
not just whitespace. It is a declared deterministic normalization policy, not a claim
that the model itself reproduced exact bytes. Raw model responses remain unchanged.
Invalid ordering, secrets, missing files and no-change stages still fail validation.

Export a successful preparation job:

```bash
git-progressor bundle-export JOB_ID data/releases/calculator.zip
git-progressor bundle-verify data/releases/calculator.zip --sha256 EXPECTED_SHA256
```

The ZIP contains a source manifest, normalized declarative plan and source files.
It excludes the local database, credentials, absolute paths and raw model response.
Every stage is independently reconstructed and validated before export and during
verification. The format uses fixed ZIP timestamps and ordering for repeatability.
Verification rejects unexpected paths, duplicate entries, mismatched checksums and
oversized archives. Current limits are 100 MiB and 10,000 ZIP entries. The expected
checksum must come from trusted state; a checksum is not a signature or authorization.
Keep the local proposal audit alongside the job history until cloud audit storage exists.

## Container release

```bash
docker build -t git-progressor:local .
docker run --rm --network none git-progressor:local --help
python deployment/smoke_container.py data/releases/calculator-feature-plan.zip --sha256 EXPECTED_SHA256
```

The container runs as a non-root user. Its allowlisted build context excludes local
data, virtual environments, Git history and secrets. Default execution prints help;
it does not call a model or start background publication. Mount writable persistent
storage at `/work/data` when using SQLite. The current worker is single-host only:
do not launch competing cloud tasks with independent copies of its database.
The base image is pinned to the digest tested on November 4, 2026. Python dependencies
still use version ranges: lock them before production deployment. Never bake API keys
into the image.

The November 4 container build and smoke test passed on Docker Desktop's Linux engine.
The smoke script checks the non-root runtime, absence of an API key and host data,
CLI startup, and independent reconstruction of a supplied bundle. It disables network,
drops capabilities, makes the root filesystem read-only and uses temporary memory-backed
storage. A trusted SHA-256 is required; the script does not derive its own trust value.
This confirms the calculator verification path, not cloud orchestration or publication.
The prior Docker startup blocker is resolved; no reset or data deletion was needed.

## Deployment sequence

1. Validate Terraform locally and configure a dedicated AWS account/region and
   remote state backend using temporary deployment credentials.
2. Review and apply the S3/ECR foundation. Existing Terraform also includes a legacy
   EC2 role; it does not implement the planned serverless worker permissions yet.
3. Build and smoke-test the container; push a unique release tag to ECR and record
   the resulting digest. Upload verified bundles to private S3 with trusted checksums.
4. Implement cloud state/leases, upload intake, secret injection and bounded task
   orchestration before enabling automatic processing of raw uploads.
5. Implement deterministic Git publication with crash reconciliation, then bind
   validated stages to the schedule and test contribution eligibility.
6. Add backlog warnings, daily contribution monitoring, costs, alerts and a prolonged
   unattended rehearsal. Daily contribution is the target, not an outage-proof guarantee.

The ECR resource is defined in `deployment/terraform/releases.tf`. No queue triggers,
Fargate tasks, publisher functions or web dashboard are deployed by the foundation.
