class GitProgressorError(Exception):
    """Base exception for expected application failures."""


class IntakeError(GitProgressorError):
    """Project intake could not complete safely."""


class SecretDetectedError(IntakeError):
    """A likely credential was found in the source tree."""


class InvalidPlanError(GitProgressorError):
    """A plan violates the structured plan contract."""


class PublicationDisabledError(GitProgressorError):
    """Publication is unavailable in this scaffold."""

