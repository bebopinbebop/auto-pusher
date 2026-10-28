from git_progressor.planner.contracts import PlanningRequest


class OpenAIPlanner:
    """Reserved Responses API adapter; intentionally inert in this scaffold."""

    def create_plan(self, request: PlanningRequest) -> str:
        raise NotImplementedError("live OpenAI planning is not implemented in this milestone")

