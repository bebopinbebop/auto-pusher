from __future__ import annotations

from pathlib import Path

from git_progressor.exceptions import IntakeError
from git_progressor.intake.ignore import load_ignore_spec


def scan_project(root: Path, max_file_bytes: int) -> list[Path]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise IntakeError(f"project directory does not exist: {root}")
    spec = load_ignore_spec(root)
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise IntakeError(f"symbolic links are not accepted during intake: {relative}")
        if path.is_file() and not spec.match_file(relative):
            if path.stat().st_size > max_file_bytes:
                raise IntakeError(f"file exceeds configured size limit: {relative}")
            files.append(path)
    if not files:
        raise IntakeError("project contains no ingestible files")
    return files

