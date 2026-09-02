from pathlib import Path

from git_progressor.models import ProjectManifest, ProjectPlan


class OpenAIPlanner:
    """Reserved Responses API adapter; intentionally inert in this scaffold."""

    def create_plan(self, source: Path, manifest: ProjectManifest) -> ProjectPlan:
        raise NotImplementedError("live OpenAI planning is not implemented in this milestone")

