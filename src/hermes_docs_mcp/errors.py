"""Typed errors, mirroring the separation used by the other MCPs in this repo."""


class DocsError(Exception):
    """Base error."""


class DocsConfigError(DocsError):
    """Environment or cache directory is unusable."""


class DocsInputError(DocsError):
    """A tool argument failed validation, or a page reference does not exist."""


class DocsOfflineError(DocsError):
    """Cache is missing or stale and the network is disabled."""


class DocsFetchError(DocsError):
    """The docs site returned a non-2xx status or an unusable payload."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
