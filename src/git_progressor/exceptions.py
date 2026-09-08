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


class ProjectNotFoundError(GitProgressorError):
    """A requested imported project does not exist."""


class StageGenerationError(GitProgressorError):
    """A deterministic stage could not be generated safely."""


class StageValidationError(GitProgressorError):
    """Generated stages failed independent validation."""


class DiscoveryError(GitProgressorError):
    """A project collection could not be discovered safely."""


class IdentityConflictError(GitProgressorError):
    """A candidate cannot be matched to a logical project confidently."""


class AnalysisError(GitProgressorError):
    """A source revision could not be analyzed safely."""
