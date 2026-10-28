# EC2 deployment scaffold

The [Terraform foundation](../terraform/README.md) defines the dedicated private artifact
bucket and EC2 instance profile. It does not yet launch or configure a worker instance.

Use a dedicated `git-progressor` account, store application data under
`/var/lib/git-progressor`, and provision repository SSH deployment keys outside the
application directory. The supplied systemd unit is intentionally inactive until the
publisher worker exists. Secrets should be injected from AWS Secrets Manager or SSM.

