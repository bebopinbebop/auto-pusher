from contextlib import AbstractContextManager
from typing import Protocol


class ProjectLock(Protocol):
    def acquire(self, project_id: str, owner_id: str) -> AbstractContextManager[None]: ...

