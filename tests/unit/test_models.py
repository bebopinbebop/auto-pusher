import pytest
from pydantic import ValidationError

from git_progressor.models import ProjectPlan


def valid_plan() -> dict:
    return {
        "project_summary": "A calculator",
        "strategy": "Build core before tests",
        "stages": [
            {
                "number": 1,
                "title": "Core",
                "description": "Add arithmetic",
                "files_added": ["calculator.py"],
                "reasoning": "Core behavior comes first",
                "suggested_commit_message": "feat: add calculator",
            },
            {
                "number": 2,
                "title": "Tests",
                "description": "Add coverage",
                "files_added": ["tests/test_calculator.py"],
                "reasoning": "Verify behavior",
                "suggested_commit_message": "test: cover calculator",
            },
        ],
    }


def test_rejects_malformed_plan() -> None:
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate({"project_summary": "missing everything"})


def test_rejects_impossible_stage_order() -> None:
    value = valid_plan()
    value["stages"][1]["number"] = 3
    with pytest.raises(ValidationError, match="ordered and contiguous"):
        ProjectPlan.model_validate(value)


def test_rejects_overlapping_file_operations() -> None:
    value = valid_plan()
    value["stages"][0]["files_modified"] = ["calculator.py"]
    with pytest.raises(ValidationError, match="multiple operations"):
        ProjectPlan.model_validate(value)


def test_rejects_unknown_fields() -> None:
    value = valid_plan()
    value["unexpected"] = True
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(value)

