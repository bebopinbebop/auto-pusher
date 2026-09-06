# Security model

Intake excludes common generated and credential-bearing paths, rejects symlinks, limits
file size, and scans filenames and content before copying. Findings report only file paths
and rule names. The scanner is intentionally conservative and is not a substitute for a
dedicated secret-scanning engine.

Stage operations accept only validated relative POSIX paths. Windows separators, drive
prefixes, parent traversal, NULs, and symlinks are rejected. Content is copied from the
immutable source or decoded from strict base64; it is never executed. Every snapshot is
rescanned, including on repeated validation. Reports contain paths and rule identifiers,
never file contents.

Tampering with a snapshot or its persisted manifest changes independently recomputed file
or tree hashes and produces an invalid result. Regeneration refuses to overwrite a stage
that no longer matches its manifest, preserving evidence for inspection.

The authoritative source remains local and read-only by convention. OS-level immutable
storage, encrypted volumes, SSH deployment-key handling, AWS secret retrieval, and a
pre-push rescan belong to later milestones. Publication fails closed and remains disabled.

Repository `.gitignore` rules exclude common private-key extensions (`*.pem`, `*.key`,
`*.p12`, and `*.pfx`) from accidental staging. Real credentials and deployment keys should
still live outside the source repository; ignore rules are not access control.

Collection discovery uses directory entry names and reads at most 1 MiB from selected
project metadata solely to obtain declared names. Full existing scanner and size-limit
enforcement occurs before every source revision copy.
