# Next milestone: one-shot cloud bundle verification

## November 17: first cloud verification passed

The verifier infrastructure is now deployed in US East 1: thirteen additions,
zero changes and zero deletions. A single Fargate task retrieved the exact S3
version of the calculator bundle, reconstructed all three stages and wrote a
`VERIFIED` report. The task stopped with exit code 0. The retrieved report matched
the trusted bundle checksum and final source revision. No model or GitHub calls
were made. No continuously running service or automatic trigger was created.

Evidence retained privately in S3 and locally under `data/cloud-verification/`:

- Bundle SHA-256: `8f2d73eb9f9ef726eda45deec2418cf4b5796e16dd5e1bfdbb7f22faade84c09`.
- Verification identity: `86a9468891042808ba4d5db3bb64365499b0e5847a3aa50d715830e2c20f3a57`.
- Report key: `reports/verification/86a9468891042808ba4d5db3bb64365499b0e5847a3aa50d715830e2c20f3a57.json`.

AWS returns explicit empty container fields; these defaults are now represented
in Terraform to avoid an unnecessary task-definition replacement. The final
post-deployment plan reports no changes. No replacement was applied.

Next: exercise duplicate execution and failure reporting, then implement durable
cloud job state and intake before enabling automatic planning. Duplicate-report
behavior has offline coverage but has not yet been exercised by a second AWS task.
Historical preparation notes below describe the state before this deployment.

## November 16 stopping point

The adapter, nine new tests, verifier Dockerfile and optional Terraform resources
are implemented. The full offline suite and lint passed. The new image passed
non-root/scratch checks and independently reconstructed the three-stage calculator
with networking disabled and a read-only root filesystem.

The private ECR release is `cloud-verifier-v1`, with registry-confirmed digest
`sha256:37c45d196cfb2414c1cf0fae995ba373f2e7c48651c8e9871bf4ef2ceb0da515`.
Its base is the prior verified worker release. No API credentials were supplied.

The Terraform preview contains 13 additions, zero changes and zero deletions.
**The verifier infrastructure has not been applied, and no cloud task has run.**
The sample bundle has not been uploaded to S3. The existing storage, registry and
shared-state foundation remain deployed. Local account settings and the saved
plan are ignored by Git.

### Resume sequence

1. Regenerate and review the verifier plan with `verification_image` set to the
   digest above in the private repository. Keep this value in both computers'
   local variable files once deployed; removing it would propose deleting the
   optional verifier resources.
2. Apply the reviewed plan, upload the verified bundle, and retain its exact S3
   version and trusted checksum. Do not infer the checksum from an untrusted event.
3. Launch one Fargate task with a public IP, the output subnet/security group and
   a `GIT_PROGRESSOR_VERIFICATION_REQUEST` JSON environment override containing
   `bucket`, `owner` (account ID), `key` under `bundles/`, `version`, and `sha256`.
4. Observe completion, retrieve `reports/verification/<request_id>.json`, verify
   its result and confirm the task has stopped. If startup stalls, stop the task;
   the ten-minute Python alarm starts only after the container entry point starts.
5. Test duplicate execution before adding automatic intake. Report writes use a
   conditional create and compare existing content on a conflict; this is not a
   distributed job queue or a publication lock.

The verifier uses the task role, never embedded AWS keys. Its execution role reads
the image and writes logs; its task role reads bundle versions and reads/writes
verification reports only. Logs expire after seven days. No ECS service, NAT
gateway or upload trigger is defined. Task runtime/public IP, logs and storage
incur usage charges; no budget alarm or hard spending cap is implemented yet.

The Python entry point is `python -m git_progressor.cloud.verify` with the `aws`
optional dependency. It bounds input size and runtime, rejects invalid references,
and prints only a status, request identity or exception type. Failure reports are
not persisted to S3 yet; orchestration must retain failure state in the next phase.
The AWS SDK performs bounded transport retries. No model or GitHub call is made.

## Starting point

The private artifact bucket, ECR repository and shared Terraform backend are
deployed in US East 1. The first container release passed offline reconstruction.
The preparation worker still relies on single-host SQLite; independent Fargate
tasks must not treat separate SQLite files as a shared job database.

## Bounded execution path

1. Upload a previously verified bundle to the versioned artifact bucket.
2. Supply a trusted request identifying its bucket, key, exact version and SHA-256.
3. Run one on-demand container task with permission to read bundle versions and
   write verification reports, without API or GitHub credentials.
4. Download with a strict size bound, verify the checksum, reconstruct all stages,
   and compare the final snapshot to the authoritative source in the bundle.
5. Write a deterministic report keyed by request identity. Duplicate execution
   must not overwrite a different report or create duplicate publication work.
6. Observe task completion and independently retrieve the report, then stop.

## Implementation and evidence

- Unit tests cover malformed references, size/checksum failures, pinned version
  retrieval, successful reconstruction and duplicate report behavior.
- Build and smoke-test a new container containing the AWS adapter before release.
- Pin the task definition to its uploaded image digest. Use separate task and
  execution roles, no inbound network rules, short log retention and no ECS service.
- Review Terraform additions before deployment. Avoid NAT gateways, always-on
  instances, public endpoints and automatic upload triggers for this milestone.
- Run one calculator verification task and record its report and exit status.

This is a manual cloud execution proof, not a raw-project AI planner, distributed
queue, publisher or daily schedule. It makes no model calls and executes no source
project code. Bounded task runtime and report recovery must be addressed before
unattended scheduling. The next phase introduces durable cloud job state and intake.
