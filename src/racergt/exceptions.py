"""Custom exceptions used by RACER-GT."""

class RacerGTError(Exception):
    """Base exception for package-specific errors."""

class InputValidationError(RacerGTError):
    """Raised when the long-form input violates the study protocol."""

class DisconnectedOverlapGraphError(RacerGTError):
    """Raised when chunk scales are not identifiable from overlap links."""

class UnbalancedDesignError(RacerGTError):
    """Raised when a balanced ANOVA/G-study is requested on unbalanced data."""
