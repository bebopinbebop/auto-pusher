# Next milestone: one-shot cloud bundle verification

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
