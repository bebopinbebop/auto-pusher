from typing import Protocol

from git_progressor.planner.contracts import PlanningRequest


class Planner(Protocol):
    def create_plan(self, request: PlanningRequest) -> str:
        """Return untrusted ProjectPlan JSON; deterministic code validates it."""
        ...

