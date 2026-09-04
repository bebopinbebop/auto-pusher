from __future__ import annotations

from pathlib import Path

from git_progressor.exceptions import StageValidationError
from git_progressor.intake.ignore import load_ignore_spec


def inspect_tree(root: Path) -> list[Path]:
    """Return every regular file after rejecting links and non-file entries."""
    if root.is_symlink():
        raise StageValidationError("snapshot root cannot be a symbolic link")
    if not root.is_dir():
        raise StageValidationError(f"snapshot directory does not exist: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise StageValidationError(f"symbolic link is not allowed: {relative}")
        if path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise StageValidationError(f"unsupported filesystem entry: {relative}")
    return files


def assert_no_ignored_files(root: Path, files: list[Path]) -> None:
    spec = load_ignore_spec(root)
    prohibited = [
        path.relative_to(root).as_posix()
        for path in files
        if spec.match_file(path.relative_to(root).as_posix())
    ]
    if prohibited:
        raise StageValidationError(
            "ignored metadata is present: " + ", ".join(sorted(prohibited))
        )
