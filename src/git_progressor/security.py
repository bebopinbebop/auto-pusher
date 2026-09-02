from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from git_progressor.exceptions import SecretDetectedError


@dataclass(frozen=True)
class SecretFinding:
    path: str
    rule: str


class CredentialScanner:
    """Conservative local scanner; findings never include secret contents."""

    BLOCKED_NAMES = {".env", "credentials", "terraform.tfstate"}
    BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
    PATTERNS = {
        "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "aws-access-key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
        "github-token": re.compile(rb"(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    }

    def scan_file(self, root: Path, path: Path) -> list[SecretFinding]:
        relative = path.relative_to(root).as_posix()
        if path.name.lower() in self.BLOCKED_NAMES or path.suffix.lower() in self.BLOCKED_SUFFIXES:
            return [SecretFinding(relative, "blocked-credential-file")]
        data = path.read_bytes()
        return [
            SecretFinding(relative, name)
            for name, pattern in self.PATTERNS.items()
            if pattern.search(data)
        ]

    def assert_safe(self, root: Path, paths: list[Path]) -> None:
        findings = [finding for path in paths for finding in self.scan_file(root, path)]
        if findings:
            summary = ", ".join(f"{item.path} ({item.rule})" for item in findings)
            raise SecretDetectedError(f"suspected credentials detected: {summary}")

