from pathlib import Path
from typing import Protocol


class SnapshotStore(Protocol):
    def materialize(self, stage_number: int, destination: Path) -> None: ...

