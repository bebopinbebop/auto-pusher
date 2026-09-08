# Project storage format

Each imported project is stored at `data/projects/<project-id>/`:

```text
manifest.json       Canonical file metadata and source tree hash
source/             Verified copy of the completed project
planning/           Future structured analysis and plan artifacts
stages/             Full snapshots plus adjacent stage manifest JSON files
state/              Future per-project operational artifacts
revisions/          Later immutable source revisions keyed by tree hash
analyses/           Version-addressed deterministic analysis artifacts
```

`source_hash` is SHA-256 over sorted POSIX relative paths and their binary SHA-256 digests.
Timestamps and permissions are not part of final-state equality; filenames and bytes are.

The static plan is stored at `planning/plan.json`. Snapshot `stages/003/` is described by
`stages/003.manifest.json`; the manifest is outside the snapshot so it cannot affect the
project tree hash. Temporary `.tmp-<stage>-<uuid>` directories are never valid stages.

The first imported revision stays at `source/` for generator compatibility. Later revisions
use `revisions/<source-hash>/source/` and an adjacent `manifest.json`. SQLite maps all
revisions to one stable logical project UUID; observed local paths are metadata only.

Analysis artifacts use
`analyses/<source-hash>/analyzer-v<version>/project-analysis.json`. The artifact contains
only typed metadata and paths. Its canonical hash excludes runtime timestamps and the
`analysis_hash` field itself, so recomputing one revision with the same analyzer version and
limits produces the same bytes and hash.
