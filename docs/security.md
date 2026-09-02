# Security model

Intake excludes common generated and credential-bearing paths, rejects symlinks, limits
file size, and scans filenames and content before copying. Findings report only file paths
and rule names. The scanner is intentionally conservative and is not a substitute for a
dedicated secret-scanning engine.

The authoritative source remains local and read-only by convention. OS-level immutable
storage, encrypted volumes, SSH deployment-key handling, AWS secret retrieval, and a
pre-push rescan belong to later milestones. Publication fails closed and is disabled now.

