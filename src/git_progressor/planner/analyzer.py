from pathlib import Path
from typing import Protocol

from git_progressor.models import ProjectManifest, ProjectPlan


class Planner(Protocol):
    def create_plan(self, source: Path, manifest: ProjectManifest) -> ProjectPlan: ...

