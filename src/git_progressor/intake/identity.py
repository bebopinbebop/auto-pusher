from __future__ import annotations

import configparser
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from git_progressor.intake.discovery import ProjectCandidate
from git_progressor.models import IdentityConfidence

MAX_MARKER_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SourceIdentity:
    value: str
    display_name: str
    confidence: IdentityConfidence
    evidence: str


class SourceIdentityResolver:
    """Resolve stable logical identity without hashing mutable source content."""

    def resolve(self, candidate: ProjectCandidate) -> SourceIdentity:
        declared = self._declared_name(candidate.path)
        if declared is not None:
            marker, name = declared
            normalized = normalize_name(name)
            material = f"declared-v1\0{marker.casefold()}\0{normalized}"
            return SourceIdentity(
                hashlib.sha256(material.encode()).hexdigest(),
                name,
                IdentityConfidence.DECLARED,
                marker,
            )
        normalized = normalize_name(candidate.path.name)
        marker_signature = "\0".join(marker.casefold() for marker in candidate.markers)
        material = f"structural-v1\0{normalized}\0{marker_signature}"
        return SourceIdentity(
            hashlib.sha256(material.encode()).hexdigest(),
            candidate.path.name,
            IdentityConfidence.STRUCTURAL,
            ",".join(candidate.markers),
        )

    def _declared_name(self, root: Path) -> tuple[str, str] | None:
        readers = (
            ("pyproject.toml", self._pyproject_name),
            ("package.json", self._package_json_name),
            ("Cargo.toml", self._cargo_name),
            ("setup.cfg", self._setup_cfg_name),
            ("go.mod", self._go_module_name),
        )
        for marker, reader in readers:
            path = root / marker
            if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_MARKER_BYTES:
                continue
            try:
                name = reader(path)
            except (
                OSError,
                UnicodeError,
                ValueError,
                IndexError,
                configparser.Error,
            ):
                continue
            if isinstance(name, str) and name.strip():
                return marker, name.strip()
        return None

    @staticmethod
    def _pyproject_name(path: Path) -> str | None:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        poetry = data.get("tool", {}).get("poetry", {})
        return project.get("name") or poetry.get("name")

    @staticmethod
    def _package_json_name(path: Path) -> str | None:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("name") if isinstance(data, dict) else None

    @staticmethod
    def _cargo_name(path: Path) -> str | None:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return data.get("package", {}).get("name")

    @staticmethod
    def _setup_cfg_name(path: Path) -> str | None:
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        return parser.get("metadata", "name", fallback=None)

    @staticmethod
    def _go_module_name(path: Path) -> str | None:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        if first_line.startswith("module "):
            return first_line.removeprefix("module ").strip()
        return None


def normalize_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "unnamed-project"
