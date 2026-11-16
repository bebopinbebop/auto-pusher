# Shared Terraform state bootstrap

This separate root prepares a private state bucket in US East 1. It creates six
resources: the bucket and its public-access block, ownership, versioning,
encryption and TLS-only policy. It creates no worker or application resources.
No expiry rule removes state history. Version storage has an ongoing usage cost.
`prevent_destroy` protects Terraform-managed deletion; it is not an IAM deny.

Use Terraform 1.10 or later on both computers for S3 native lock files. No
DynamoDB lock table is needed. Use only the default Terraform workspace.

## Bootstrap once from one computer

Authenticate with your deployment profile, copy `terraform.tfvars.example` to
`terraform.tfvars`, and replace the account placeholder. From this directory:

```bash
terraform init
terraform fmt -check
terraform validate
terraform plan -out=bootstrap.tfplan
```

Review the six additions and account before `terraform apply bootstrap.tfplan`.
Do not apply if a bucket already exists without corresponding state: investigate
ownership and recover/import the original state first. Preserve the resulting
local state securely until migration is complete. Never run a second bootstrap
from another computer with fresh local state.

## Migrate bootstrap state after creation

Copy `../terraform/backend.tf.example` to `backend.tf` in this directory. Copy
`../terraform/foundation.backend.hcl.example` to `bootstrap.backend.hcl` and
replace both account placeholders. Change its key to `bootstrap/terraform.tfstate`.
Then run:

```bash
terraform init -migrate-state -backend-config=bootstrap.backend.hcl
terraform state list
terraform plan
```

Accept migration only when Terraform identifies the intended local and S3 states.
Expect six resources and no changes after migration. Keep an encrypted backup of
the original state. Do not use `-force-copy` or remove a lock held by another run.

## Connect the application foundation

In `../terraform`, copy `backend.tf.example` to `backend.tf` and
`foundation.backend.hcl.example` to `foundation.backend.hcl`. Set the same bucket
and account; retain the distinct `foundation/terraform.tfstate` key.

```bash
terraform init -migrate-state -backend-config=foundation.backend.hcl
terraform plan -out=foundation-remote.tfplan
```

Review the fresh foundation plan before applying; discard old local-backend plans.
With no deployed foundation, expect seven additions. On the second computer,
configure identical files and use `terraform init -backend-config=foundation.backend.hcl`.
Never accept a state migration from an unrelated local checkout. Keep both roots
on the default workspace, and do not use `-lock=false`.

## Access and recovery

Backend access is for infrastructure operators only, never the application worker.
The deployment identity needs `s3:ListBucket` on the bucket, `s3:GetObject` and
`s3:PutObject` on each of the two state keys, and `s3:GetObject`, `s3:PutObject`,
`s3:DeleteObject` on each matching `.tflock` key. Resource provisioning needs
additional permissions. This configuration does not grant new IAM access.
Keep credentials in your authenticated profile, never backend files. Local
backend configuration, state and plans are Git-ignored; provider locks are tracked.

If an operation is interrupted, inspect the active process and lock owner before
unlocking. Recover damaged state from version history only after stopping all
writers and comparing lineage/serial with backups. State may contain sensitive
values; do not attach it to public issues or logs.

See [HashiCorp's S3 backend documentation](https://developer.hashicorp.com/terraform/language/backend/s3)
for locking and backend permissions. A validated plan is not a deployed backend;
record migration and a no-change bootstrap plan before declaring shared state ready.
