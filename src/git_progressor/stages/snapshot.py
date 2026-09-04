from pathlib import Path
from typing import Protocol

from git_progressor.models import StageManifest


class SnapshotStore(Protocol):
    def materialize(self, stage_number: int, destination: Path) -> StageManifest: ...
