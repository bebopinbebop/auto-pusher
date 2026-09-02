from pathlib import Path
from typing import Protocol

from git_progressor.models import ProjectManifest


class StageValidator(Protocol):
    def validate_final_state(self, final_stage: Path, manifest: ProjectManifest) -> None: ...

