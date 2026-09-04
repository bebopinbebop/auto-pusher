import hashlib
import json

from git_progressor.models import ProjectPlan


def plan_json_schema() -> dict[str, object]:
    return ProjectPlan.model_json_schema()


def parse_plan_json(value: str) -> ProjectPlan:
    return ProjectPlan.model_validate_json(value)


def plan_sha256(plan: ProjectPlan) -> str:
    canonical = json.dumps(
        plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
