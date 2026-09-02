from pathlib import Path

from pathspec import PathSpec

DEFAULT_EXCLUSIONS = (
    ".git/",
    ".env",
    ".venv/",
    "venv/",
    "__pycache__/",
    "node_modules/",
    ".terraform/",
    "*.tfstate",
    "*.tfstate.*",
    "dist/",
    "build/",
    ".idea/",
    ".vscode/",
)


def load_ignore_spec(root: Path) -> PathSpec:
    patterns = list(DEFAULT_EXCLUSIONS)
    ignore_file = root / ".gitignore"
    if ignore_file.is_file():
        patterns.extend(ignore_file.read_text(encoding="utf-8", errors="replace").splitlines())
    return PathSpec.from_lines("gitwildmatch", patterns)

