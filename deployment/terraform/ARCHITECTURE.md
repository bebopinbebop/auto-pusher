# Serverless-first deployment plan

Status: target design, not deployed. Existing Terraform creates only the private S3
foundation and a legacy EC2 role/profile. The resources below are implementation work,
not claims about an operational service. No always-on EC2 worker is planned by default.

## End-to-end flow

1. Either computer uploads a project archive and a completion manifest to private S3.
2. An S3 event for the completion manifest enters a standard SQS intake queue.
3. A small dispatcher Lambda validates event identity and conditionally records a job in
   DynamoDB, then starts a Step Functions Standard execution with a stable job identity.
4. The workflow starts an ECS Fargate planning task and waits for it to finish. That task
   imports the exact S3 version, analyzes the project, calls the AI provider under limits,
   reconstructs stages, and validates them. It never has GitHub publishing credentials.
5. Passing artifacts are stored under immutable S3 keys. DynamoDB records validation
   policy, hashes, stage order, and schedule membership. No human approval gate exists.
6. EventBridge Scheduler invokes a short dispatcher during the Tokyo evening window.
   It finds due work using a DynamoDB due-time index and sends identities to a publisher
   queue. The saved schedule, not queue arrival order, determines execution order.
7. A publisher Lambda claims a fenced lease, verifies exact artifacts and remote state,
   performs the pending Git operation, and reconciles success before marking the job done.
   Git is packaged in its container image. It never calls the AI provider.

The publisher Lambda is conditional on measured clone/apply/push duration and temporary
disk usage fitting ordinary Lambda limits with retry headroom. Larger repositories use
a short-lived Fargate publisher task behind the same job interface. Do not silently let
a task overrun a Lambda deadline or introduce always-on compute to mask that problem.

## Storage and application releases

One application-data bucket is sufficient initially. S3 prefixes are key namespaces,
not actual directories; permissions enforce separation.

| Prefix or store | Contents | Writer |
| --- | --- | --- |
| `uploads/<project>/<upload>/` | Raw archives | Authenticated uploader |
| `incoming/<upload>/complete.json` | Version/checksum/size references, written last | Uploader |
| `sources/<project>/<revision>/` | Verified imported source | Planning worker |
| `planning/<project>/<revision>/` | Requests/results and validation evidence | Planning worker |
| `bundles/<project>/<plan>/` | Stage snapshots, hashes, messages | Planning worker |
| `reports/` | Redacted job summaries | Workers |
| Private ECR repository | Git Progressor worker container releases | Deployment identity |
| DynamoDB | Jobs, projects, stage state, schedule, leases, usage reservations | Scoped workers |
| Secrets Manager | AI and GitHub credentials | Secret administration identity |

Source uploads are untrusted input, never application releases. Workers cannot update ECR
images. Pin task/function releases by image digest; deploy via a separate build process.
EC2 user data is not needed for this target. If EC2 is retained as a fallback, user data
should only bootstrap a pinned release, not embed the application or credentials.

Terraform state belongs in a separate, encrypted remote-state backend with locking and
restricted deployment access. Reuse an existing backend if available; otherwise bootstrap
a dedicated state bucket separately. This second bucket is for infrastructure state,
not for the application code or ordinary project data.

## Planned Terraform resource groups

| Group | Resource families | Implementation status |
| --- | --- | --- |
| Artifact storage | S3 bucket, encryption, ownership, public block, TLS policy | Present |
| Releases | ECR repository, immutable tags, lifecycle policy | Planned |
| Durable state | DynamoDB on-demand table, due-time index, recovery settings | Planned |
| Intake | SQS queue/DLQ, S3 notification, restricted queue policy | Planned |
| Orchestration | Dispatcher Lambda, event source mapping, Standard workflow | Planned |
| Planning | ECS cluster/task definition, Fargate network, task/execution roles | Planned |
| Publication | Lambda container, queue/DLQ, event source mapping, scheduler | Planned |
| Credentials | Secret containers and role grants; values entered outside Terraform | Planned |
| Operations | CloudWatch logs/alarms, notification topic, AWS budget | Planned |
| Remote state | Separate backend bootstrap/configuration | Planned |

Remove or make the existing EC2-only role/profile opt-in when implementing worker roles;
do not grant Lambda or ECS access by reusing the EC2 trust policy. Bucket management stays
in the existing Terraform state to avoid replacement. Do not enable event sources until
worker code, secret references, and recovery tests are ready.

## Network and cost decisions

Use ordinary on-demand Lambda without provisioned concurrency or a customer VPC for the
short control/publishing functions. The planning task needs outbound HTTPS to the model
provider. Initial Fargate design: public subnet, assigned public IP, no inbound security
group rules, outbound access only as required. This avoids an always-on NAT gateway, but
public IPv4 has a charge during task execution. Use an S3 gateway endpoint where suitable.
Private subnets plus NAT/endpoints remain an alternative if isolation requirements change.

Do not run an ECS service with a minimum task count: run individual tasks and stop them
when finished. Keep source project code out of the execution path; future test execution
requires a separate isolated task without cloud or GitHub credentials.

S3, ECR, DynamoDB, Lambda, and Fargate are usage-priced, not flat monthly subscriptions.
Persistent storage, object versions, logs, secrets, requests, transfer, workflow transitions,
and public IP use can still cost money when planning traffic is low. Remote AI computation
does not itself require a large EC2 instance; snapshot reconstruction determines worker
memory and disk requirements.

The USD 100/month target needs a region-specific estimate before deployment. Do not assume
free-tier eligibility or claim serverless is always cheaper. Measure archive size, expanded
size, stage count, planner runtime, model tokens, clone size, and publisher duration with
the calculator and a representative real project. Price a normal month and a burst/retry
month. Confirm whether the ceiling includes AI-provider charges before enabling calls.

Cost controls to implement:

- One concurrent planning task initially; reserve admission atomically in DynamoDB.
- Per-project model token, call-count, stage-count and wall-clock limits.
- Aggregate model-usage reservation before calls; conservatively account for uncertain calls.
- Maximum archive expansion, file count, snapshot bytes, and log volume.
- Bounded retries and DLQs; no infinite automatic replanning loop.
- Configurable log/image retention, incomplete-upload expiry, and source-version retention.
- Budget alerts at configurable thresholds; alerts are not a hard spending cap.
- Authenticated uploads with quotas; a runaway uploader must not trigger unbounded processing.

## Correctness and unattended operation

S3 and standard SQS can deliver duplicates or out of order. Use bucket/key/version plus
validated content identity for deduplication, not just an event ID. Pin upload versions,
reject unsafe archive paths/links and expansion bombs, and verify completion references.
Processing writes use compare-and-set transitions. Expired leases require recovery;
DynamoDB TTL deletion is asynchronous and must not decide lock ownership.

Do not acknowledge intake merely because a task launch was attempted. Start the durable
workflow idempotently; distinguish launch failure from running-work failure. Workflow
timeouts, task crashes, and duplicate notifications must lead to a recoverable job record.
Publication must reconcile a successful remote push after a crash before retrying.

Append new projects after existing scheduled work without redrawing saved slots. Exclude
failed projects from publishable coverage and show them separately. A missing predecessor
blocks its own project, not unrelated work. Preserve the configured daily total and evening
window when rescheduling missed jobs; expose forecast changes in reports.

The later status website should read a restricted status API or generated report, with
authentication. It does not require a continuously running EC2 web server. Do not expose
source files, raw model inputs, credentials, or full worker logs publicly.

## Deployment sequence

### Status website and costs

Serve a static application through CloudFront from a private S3 origin. Restrict origin
access to the website prefix or a dedicated website bucket, never project source prefixes.
Origin Access Control protects the origin, not viewer identity: add user authentication
and an authenticated read-only API for operational/cost data. API Gateway plus Lambda can
serve DynamoDB status without an always-running web server. Avoid publicly cached private
API responses. A static frontend can display changing information fetched from that API.

Show project progress, queue coverage, next stage, failures, and data freshness. For costs,
show month-to-date AWS charges, service breakdown, budget remaining, and a forecast when
available. Activate project cost-allocation tags and label unallocated costs separately;
account-wide charges must not be mislabeled as this application's charges.

A scheduled collector caches Cost Explorer results once daily instead of billing an API
request on every page view. Billing data can lag and estimated charges can be revised;
display the collection time and estimated/final status. Keep API permissions in the
collector role, never the browser. AWS Budgets supplies independent actual/forecast alerts,
not the dashboard's live transaction ledger or a guaranteed spending cutoff.

Track external model usage separately from AWS costs using recorded tokens and versioned
rates, clearly marked as estimates until reconciled with provider billing. Do not label
AWS-only cost totals as combined spending. These dashboard resources and cost collection
are planned work, not currently deployed.

References: [Cost Explorer freshness](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-enable.html),
[Cost Explorer API pricing](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/),
[CloudFront private content](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-overview.html).

1. Implement durable job transitions and cloud-store interfaces locally, with duplicate and
   crash tests; retain SQLite for local development only.
2. Implement container entrypoints, bounded live planning, bundle verification and real Git
   recovery; measure runtime/storage before choosing final task sizing.
3. Add ECR, DynamoDB, queues, roles and container deployment in Terraform with triggers off.
4. Exercise one upload through planning, validation and test-repository publication.
5. Enable scheduling, limits and alerts; rehearse unattended operation before production use.

## AWS references

- [S3 event delivery and destinations](https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-how-to-event-types-and-destinations.html)
- [Ordinary Lambda limits and other execution modes](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [Lambda container images in ECR](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html)
- [Lambda pricing](https://aws.amazon.com/lambda/pricing/)
- [Fargate pricing](https://aws.amazon.com/fargate/pricing/)
