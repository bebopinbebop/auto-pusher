from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from git_progressor.exceptions import DiscoveryError

EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".idea",
        ".terraform",
        ".venv",
        ".vscode",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)

EXACT_MARKERS = frozenset(
    {
        ".git",
        "build.gradle",
        "build.gradle.kts",
        "CMakeLists.txt",
        "Cargo.toml",
        "go.mod",
        "package.json",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
    }
)

SOURCE_DIRECTORIES = frozenset({"app", "lib", "src"})


@dataclass(frozen=True)
class ProjectCandidate:
    path: Path
    markers: tuple[str, ...]


class ProjectBoundaryDetector:
    """Conservative, replaceable project-boundary heuristics."""

    def markers(self, directory: Path) -> tuple[str, ...]:
        try:
            entries = tuple(directory.iterdir())
        except OSError as exc:
            raise DiscoveryError(f"cannot inspect directory {directory}: {exc}") from exc
        names = {entry.name for entry in entries}
        markers = {name for name in names if name in EXACT_MARKERS}
        markers.update(
            entry.name
            for entry in entries
            if entry.is_file()
            and entry.suffix.lower() in {".csproj", ".sln", ".tf"}
        )
        has_readme = any(name.lower().startswith("readme") for name in names)
        if has_readme and SOURCE_DIRECTORIES & names:
            markers.add("README+source")
        return tuple(sorted(markers, key=str.casefold))


class ProjectDiscovery:
    """Discover topmost project boundaries below a collection root."""

    def __init__(self, detector: ProjectBoundaryDetector | None = None):
        self.detector = detector or ProjectBoundaryDetector()

    def discover(self, root: Path) -> tuple[ProjectCandidate, ...]:
        root = root.expanduser().resolve()
        if root.is_symlink() or not root.is_dir():
            raise DiscoveryError(f"collection root is not a safe directory: {root}")
        candidates: list[ProjectCandidate] = []
        self._walk_children(root, candidates)
        return tuple(sorted(candidates, key=lambda item: item.path.as_posix().casefold()))

    def _walk_children(
        self, directory: Path, candidates: list[ProjectCandidate]
    ) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise DiscoveryError(f"cannot inspect directory {directory}: {exc}") from exc
        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            if child.name.casefold() in EXCLUDED_DIRECTORIES:
                continue
            markers = self.detector.markers(child)
            if markers:
                candidates.append(ProjectCandidate(child.resolve(), markers))
                continue
            self._walk_children(child, candidates)

