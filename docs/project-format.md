# Project storage format

Each imported project is stored at `data/projects/<project-id>/`:

```text
manifest.json       Canonical file metadata and source tree hash
source/             Verified copy of the completed project
planning/           Future structured analysis and plan artifacts
stages/             Future reconstructable full snapshots
state/              Future per-project operational artifacts
```

`source_hash` is SHA-256 over sorted POSIX relative paths and their binary SHA-256 digests.
Timestamps and permissions are not part of final-state equality; filenames and bytes are.

