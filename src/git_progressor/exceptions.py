class GitProgressorError(Exception):
    """Base exception for expected application failures."""


class IntakeError(GitProgressorError):
    """Project intake could not complete safely."""


class SecretDetectedError(IntakeError):
    """A likely credential was found in the source tree."""


class InvalidPlanError(GitProgressorError):
    """A plan violates the structured plan contract."""


class PlannerRequestError(InvalidPlanError):
    """An allowlisted diagnostic, never a raw provider message."""

    CATEGORIES = {
        "authentication", "permission", "not_found", "rate_or_quota",
        "bad_request", "server", "timeout", "connection", "unknown",
    }

    def __init__(self, category: str):
        self.category = category if category in self.CATEGORIES else "unknown"
        super().__init__(
            f"OpenAI request failed ({self.category}); no automatic retry performed"
        )


class PublicationDisabledError(GitProgressorError):
    """Publication is unavailable in this scaffold."""


class PlannerResponseError(InvalidPlanError):
    """Safe response diagnostics without model text or provider error bodies."""

    CATEGORIES = {"incomplete", "refusal", "empty_or_oversized", "schema", "unknown"}

    def __init__(self, category: str):
        self.category = category if category in self.CATEGORIES else "unknown"
        super().__init__(f"OpenAI response rejected ({self.category})")


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
