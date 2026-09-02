from git_progressor.models import ProjectPlan


def plan_json_schema() -> dict[str, object]:
    return ProjectPlan.model_json_schema()


def parse_plan_json(value: str) -> ProjectPlan:
    return ProjectPlan.model_validate_json(value)

