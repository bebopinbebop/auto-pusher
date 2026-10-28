from collections import Counter
from datetime import date, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from git_progressor.cli import app
from git_progressor.publisher.schedule import (
    DraftSchedule,
    QueueProject,
    ScheduleQueue,
    build_schedule,
    forecast_lines,
    save_schedule,
)


def queue():
    return ScheduleQueue(projects=tuple(
        QueueProject(project_id=UUID(int=i), name=f"project-{i}",
                     plan_hash=str(i) * 64, stage_count=25)
        for i in (1, 2)
    ))


def test_schedule_is_repeatable_ordered_and_within_daily_limits():
    source = queue()
    result = build_schedule(source, date(2026, 11, 1), "departure")
    assert result == build_schedule(source, date(2026, 11, 1), "departure")
    assert result != build_schedule(source, date(2026, 11, 1), "different")
    assert [(s.project_id, s.stage_number) for s in result.stages] == [
        (p.project_id, n) for p in source.projects for n in range(1, 26)
    ]
    times = [s.publish_after for s in result.stages]
    assert times == sorted(set(times))
    assert all(20 <= t.hour < 23 and t.utcoffset() == timedelta(hours=9) for t in times)
    counts = Counter(t.date() for t in times)
    assert all(1 <= count <= 3 for count in counts.values())
    assert len(counts) == (times[-1].date() - times[0].date()).days + 1
    assert result.status == "DRAFT"
    assert "50 stages" in forecast_lines(result)[-1]


def test_empty_and_duplicate_queue():
    empty = build_schedule(ScheduleQueue(projects=()), date(2026, 11, 1), "test")
    assert not empty.stages
    assert "0 days" in forecast_lines(empty)[-1]
    with pytest.raises(ValidationError):
        ScheduleQueue(projects=(queue().projects[0],) * 2)


def test_save_does_not_overwrite_and_roundtrips(tmp_path):
    schedule = build_schedule(queue(), date(2026, 11, 1), "test")
    path = tmp_path / "schedule.json"
    save_schedule(schedule, path)
    original = path.read_bytes()
    assert DraftSchedule.model_validate_json(original) == schedule
    with pytest.raises(FileExistsError):
        save_schedule(schedule, path)
    assert path.read_bytes() == original


def test_preview_cli(tmp_path):
    source = tmp_path / "queue.json"
    source.write_text(queue().model_dump_json(), encoding="utf-8")
    output = tmp_path / "schedule.json"
    args = ["schedule-preview", str(source), "--start", "2026-11-01",
            "--seed", "test", "--output", str(output)]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "DRAFT ONLY" in result.output
    assert "50 stages" in result.output
    assert runner.invoke(app, args).exit_code == 1
    args[3] = "not-a-date"
    assert runner.invoke(app, args).exit_code == 1
