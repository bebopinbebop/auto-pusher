from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from git_progressor.exceptions import PublicationDisabledError


@dataclass(frozen=True)
class PublicationRequest:
    project_id: UUID
    stage_number: int
    repository: Path
    remote_url: str
    branch: str
    expected_parent_sha: str
    commit_message: str


class Publisher(Protocol):
    def publish(self, request: PublicationRequest) -> str: ...


class DisabledPublisher:
    def publish(self, request: PublicationRequest) -> str:
        raise PublicationDisabledError("Git publication is disabled in this scaffold")

