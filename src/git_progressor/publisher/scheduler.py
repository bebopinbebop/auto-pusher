from datetime import datetime
from typing import Protocol


class Scheduler(Protocol):
    def enqueue_due(self, now: datetime) -> int: ...

