class CoreMutationError(Exception):
    """Base mutation pipeline error."""


class MutationTooSlowError(CoreMutationError):
    """Raised when a core-state mutation exceeds the max duration budget."""


class HotUserBackpressureError(CoreMutationError):
    """Raised when a hot-user queue exceeds the configured cap."""
