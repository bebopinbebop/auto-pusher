# AWS foundation

Terraform manages the private artifact bucket and dedicated EC2 role/profile. This is
foundation scaffolding, not a running publisher deployment. It creates no EC2 instances,
networking, public HTTP endpoints, schedules, credentials, or GitHub repositories.

The bucket blocks public access, disables ACLs, enables versioning and AES256 encryption,
and denies non-TLS access. Terraform prevents accidental bucket destruction. Versioning
is recovery protection, not immutable approval: bundle hashes and trusted approval must
still be verified by the future worker. Noncurrent versions accumulate storage charges;
choose retention after defining recovery requirements.

The publisher can read `bundles/` and write `reports/` in this bucket. It cannot modify or
delete source bundles. Upload permissions for Mac/Windows sign-ins and future GitHub
secret access are intentionally not granted by this foundation.

## Local checks

```bash
cd deployment/terraform
terraform init -backend=false
terraform fmt -check
terraform validate
```

Initialization downloads providers but does not create AWS resources. Keep the generated
`.terraform.lock.hcl` in Git to pin provider checksums and selected versions.

## Future deployment

Authenticate locally using a dedicated AWS profile with temporary credentials. Set
`AWS_PROFILE` in the shell; never put keys in Terraform files. Copy the example variable
file to `terraform.tfvars` and supply your account ID and unique bucket name.

```bash
terraform plan -out=foundation.tfplan
```

Review the plan and costs before applying. The account ID guard rejects an unexpected
login. Deployment credentials need permissions to manage these S3 and IAM resources;
they are separate from the restricted runtime role.

This foundation currently uses local state. Before applying from either computer, choose
one deployment owner or configure a separate encrypted, access-controlled remote backend
with locking. Do not manage one deployment from two independent local state files. State
and saved plans are sensitive and excluded from Git. Do not use the artifact bucket as
an unconfigured substitute for a state backend or transactional publisher database.

The USD 100/month ceiling is a design constraint, not an enforced cap. Budget alerts,
worker costs, retention, authentication, and unattended recovery remain deployment tasks.

References: [AWS provider S3 bucket](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket),
[EC2 instance profile](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_instance_profile).
