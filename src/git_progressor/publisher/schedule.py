"""Local draft schedules; these artifacts do not authorize publication."""

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from git_progressor.models import StrictModel

TOKYO = timezone(timedelta(hours=9))


class QueueProject(StrictModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_count: int = Field(gt=0, le=10000)


class ScheduleQueue(StrictModel):
    projects: tuple[QueueProject, ...] = Field(max_length=1000)

    @model_validator(mode="after")
    def unique_projects(self):
        ids = [project.project_id for project in self.projects]
        if len(ids) != len(set(ids)):
            raise ValueError("each project may appear only once in the queue")
        if sum(project.stage_count for project in self.projects) > 100000:
            raise ValueError("queue exceeds 100000 stages")
        return self


class ScheduledStage(StrictModel):
    project_id: UUID
    plan_hash: str
    stage_number: int
    publish_after: datetime


class DraftSchedule(StrictModel):
    schema_version: Literal[1] = 1
    status: Literal["DRAFT"] = "DRAFT"
    timezone: Literal["Asia/Tokyo"] = "Asia/Tokyo"
    seed: str
    start_date: date
    queue: ScheduleQueue
    stages: tuple[ScheduledStage, ...]


def _draw(seed: str, day: date, label: str, bound: int) -> int:
    # Rejection sampling avoids modulo bias and does not depend on Python's RNG version.
    limit = 2**256 - (2**256 % bound)
    attempt = 0
    while True:
        payload = json.dumps([1, seed, day.isoformat(), label, attempt]).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(payload).digest(), "big")
        if value < limit:
            return value % bound
        attempt += 1


def build_schedule(queue: ScheduleQueue, start_date: date, seed: str) -> DraftSchedule:
    """Choose 1-3 total stages per Tokyo evening, preserving project/stage order."""
    pending = [
        (project, number)
        for project in queue.projects
        for number in range(1, project.stage_count + 1)
    ]
    stages = []
    offset = 0
    day = start_date
    while offset < len(pending):
        count = min(1 + _draw(seed, day, "count", 3), len(pending) - offset)
        available = list(range(3 * 60 * 60))
        seconds = sorted(
            available.pop(_draw(seed, day, f"slot:{slot}", len(available)))
            for slot in range(count)
        )
        for second in seconds:
            project, number = pending[offset]
            stages.append(ScheduledStage(
                project_id=project.project_id,
                plan_hash=project.plan_hash,
                stage_number=number,
                publish_after=datetime.combine(day, time(20), TOKYO) + timedelta(seconds=second),
            ))
            offset += 1
        if offset < len(pending):
            day += timedelta(days=1)
    return DraftSchedule(seed=seed, start_date=start_date, queue=queue, stages=tuple(stages))


def save_schedule(schedule: DraftSchedule, path: Path) -> None:
    """Create a draft once; never silently replace an existing schedule."""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(schedule.model_dump_json(indent=2) + "\n")


def forecast_lines(schedule: DraftSchedule) -> list[str]:
    lines = ["DRAFT ONLY: no approval, jobs, commits, or pushes are created."]
    for project in schedule.queue.projects:
        entries = [stage for stage in schedule.stages if stage.project_id == project.project_id]
        days = len({stage.publish_after.date() for stage in entries})
        lines.append(
            f"{project.name}: {len(entries)} stages, {days} publication days, "
            f"{entries[0].publish_after.isoformat()} to {entries[-1].publish_after.isoformat()}"
        )
    if schedule.stages:
        end = schedule.stages[-1].publish_after.date()
        days = (end - schedule.start_date).days + 1
        lines.append(
            f"Total: {len(schedule.stages)} stages across {days} calendar days; ends {end}"
        )
    else:
        lines.append("Queue empty: 0 stages, 0 days of coverage.")
    return lines
