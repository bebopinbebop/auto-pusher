# AWS handoff readiness

Artifact storage and application release storage were deployed on November 16,
2026 in US East 1. The unattended planner and publisher are not deployed.

## November 16 deployment result

- Created the private Terraform state bucket and five protection resources.
- Migrated bootstrap state into S3 and configured the foundation with a separate
  state key in that bucket. Both backends enable encryption and native S3 locking.
- Created the private artifact bucket, its five protection resources, and the
  immutable-tag ECR worker repository. No existing resources were changed or deleted.
- Bootstrap and foundation verification after deployment reported no changes.
  Both remote state objects were confirmed present, with no remaining lock files.
  Both roots use
  account guards; local backend values, plans and state backups remain Git-ignored.

The next step is uploading a tested container release and verified bundle, then
implementing cloud intake and durable job orchestration. No container image,
project bundle, API credential, queue, worker, schedule or dashboard was deployed
in this foundation step. Budget alerts remain unfinished. Cross-computer lock
contention has not been tested; normal Terraform operations acquired and released
the configured locks successfully.

## Preparation and portable artifacts

### November 16 container release

After the infrastructure milestone was committed and pushed, a fresh image was
built from commit `6bbb4b52eafdd3e3ef387a31d680d26fa8f4f043` and uploaded to the
private `git-progressor-worker` ECR repository in US East 1.

- Immutable release tag: `git-6bbb4b5`.
- Registry-confirmed digest: `sha256:6cdc3b698a9ae2496255577c3b152142bf0bb87eecaf45e372f9f3008b2184b4`.
- Offline smoke checks passed: non-root runtime, no API key or host data,
  CLI startup, and independent verification of all three calculator stages.
- Verification used a read-only root filesystem, no network, dropped capabilities,
  and the previously recorded trusted bundle checksum.

The temporary registry login was removed after upload. Use the digest for future
task definitions. This release is available in AWS but no cloud task is running.
An image upload and smoke test do not establish vulnerability-scan clearance or
production readiness. Python dependency locking, cloud job state, task permissions
and orchestration remain outstanding. The calculator bundle has not been uploaded.

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
2. Review and apply the S3/ECR foundation in `us-east-1`. The legacy EC2 role is
   disabled by default; serverless worker permissions are not implemented yet.
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

## Resume checklist: shared Terraform state

The [bootstrap configuration and runbook](../deployment/terraform-state/README.md)
now define the separate state bucket, native S3 locking, backend migration and
second-computer setup. Backend templates remain inactive until the bucket exists.
This is preparation, not evidence of a completed deployment or state migration.

On November 16, 2026, AWS identity verification succeeded and both Terraform
roots passed formatting and configuration validation. Fresh plans proposed six
bootstrap additions and seven foundation additions, each with zero changes or
deletions. No apply ran. The foundation preview still uses local state; regenerate
it after creating the state bucket and migrating to the shared backend. Lock
contention and cross-computer access remain deployment checks, not tested behavior.

The next session should establish shared infrastructure state before deployment.
The November 4 plan was a local-state preview: seven additions, no changes and no
deletions. Recreate that preview after configuring the backend; do not treat the
saved plan as ready for a different backend or a different account.

- Confirm the deployment identity and account guard, with AWS resources in
  `us-east-1`. Keep the publication schedule on Tokyo time.
- Prepare a separate state-storage bootstrap with restricted access, encryption,
  versioning and locking. Keep application artifacts separate from Terraform state.
- Configure both computers to use the same backend and state key before either
  computer manages the foundation. Keep credentials and account-specific values
  outside Git.
- Regenerate and inspect the foundation plan. Resolve unexpected changes or
  deletions before applying; the intended foundation is private S3 storage and ECR.
- After deployment, record the outputs and tested image digest, then verify one
  uploaded bundle before enabling any automatic processing.

Completion evidence for this next milestone is a shared backend configuration,
a reviewed replacement plan, and a documented deployment result. Creating storage
alone does not enable the cloud planner, Git publisher, or daily contributions.
See the [foundation guide](../deployment/terraform/README.md) for current settings.

## Recover a preparation before exporting it

Keep the planning request ID printed by `prepare-openai` and the preparation job
ID reported by `planning-status`. They identify different records. Replace the
uppercase placeholders below with those saved IDs.

```bash
git-progressor planning-status REQUEST_ID
git-progressor preparation-status JOB_ID
```

Use the recorded state to choose the next action.

| Recorded state | Recovery action |
| --- | --- |
| Planning is `CAPTURED`, preparation is pending | Run `git-progressor planning-resume REQUEST_ID` to process the saved response. |
| Planning is `CAPTURED`, preparation is `FAILED` | Inspect the preparation error, address its cause, then use `git-progressor planning-resume REQUEST_ID --retry`. This consumes a preparation attempt and reuses the captured response. |
| Planning is `FAILED` | Inspect the error category and usage first. `planning-retry REQUEST_ID` explicitly permits another billable API attempt when the request is eligible and below its three-attempt limit. |
| Planning is `STARTED` after an interruption | Preserve the record for investigation. The provider may have processed the request even if the response was lost. Automatic reissue is blocked. |
| Preparation is `SUCCEEDED` | Export with `bundle-export JOB_ID OUTPUT.zip`, retain its checksum, and verify the bundle before upload. |

An active preparation lease prevents another worker from taking over immediately.
After expiry, deterministic recovery can claim the job again while below the
three-attempt preparation limit. Completed artifacts
are checked for changes before reuse or export. A request created under an older
planning policy may require a new explicit planning request instead of a retry.

When reporting a failure, include the command name, sanitized error category,
request state and attempt count. Keep API keys and raw project contents out of
support messages. Save the local preparation audit alongside the bundle's checksum
so the next session can identify which response produced the release.

## Verify a bundle on another computer

Export a successful preparation and retain the SHA-256 printed by the command.
Use a new output filename for each release because export refuses to overwrite
an existing destination.

```bash
git-progressor bundle-export JOB_ID data/releases/project.zip
```

Transfer the ZIP and retrieve its expected checksum from your trusted release
record. On the receiving computer, run the installed CLI against the transferred
file, substituting the recorded checksum for the placeholder.

```bash
git-progressor bundle-verify project.zip --sha256 EXPECTED_SHA256
```

Successful verification checks the archive checksum, validates its source files,
reconstructs every stage in temporary storage, and compares the final stage with
the imported source. The receiving computer needs the application installed and
enough temporary disk space for the reconstructed snapshots. Those snapshots can
occupy more space than the ZIP because each stage contains a complete file tree.

Current archive limits are 100 MiB and 10,000 entries. Keep the exported ZIP intact.
Repacking it can change its checksum even when the source file contents match.
Record the verification result with the release checksum before proceeding to
upload or deployment.
