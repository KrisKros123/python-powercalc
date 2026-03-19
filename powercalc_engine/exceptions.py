"""Custom exceptions for powercalc_engine."""


class PowercalcError(Exception):
    """Base exception for all powercalc_engine errors."""


class ModelNotFoundError(PowercalcError):
    """Raised when no profile directory is found for the given manufacturer/model."""


class MissingLookupTableError(PowercalcError):
    """Raised when a required CSV/CSV.GZ LUT file does not exist."""


class InvalidModelJsonError(PowercalcError):
    """Raised when model.json is missing, unreadable, or has invalid JSON."""


class LutCalculationError(PowercalcError):
    """Raised when the LUT cannot produce a result (e.g. unknown effect name)."""


# ---------------------------------------------------------------------------
# Remote / download exceptions
# ---------------------------------------------------------------------------


class RemoteProfileNotFoundError(PowercalcError):
    """Raised when a profile does not exist in the remote repository."""


class RemoteAccessError(PowercalcError):
    """Raised when the remote repository cannot be reached or returns an error."""


class ProfileUpdateError(PowercalcError):
    """Raised when a profile update fails (I/O error, bad manifest, etc.)."""
