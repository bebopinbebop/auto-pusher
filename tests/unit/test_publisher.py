from pathlib import Path
from uuid import uuid4

import pytest

from git_progressor.exceptions import PublicationDisabledError
from git_progressor.publisher.publisher import DisabledPublisher, PublicationRequest


def test_publisher_is_explicitly_disabled() -> None:
    request = PublicationRequest(
        uuid4(), 1, Path("repo"), "git@example/repo.git", "main", "a" * 40, "feat: stage"
    )
    with pytest.raises(PublicationDisabledError):
        DisabledPublisher().publish(request)
