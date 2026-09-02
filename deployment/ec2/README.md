# EC2 deployment scaffold

Use a dedicated `git-progressor` account, store application data under
`/var/lib/git-progressor`, and provision repository SSH deployment keys outside the
application directory. The supplied systemd unit is intentionally inactive until the
publisher worker exists. Secrets should be injected from AWS Secrets Manager or SSM.

