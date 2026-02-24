class RiskEngineError(Exception):
    """Base risk engine error."""


class InputValidationError(RiskEngineError):
    """Raised for invalid user-provided inputs."""


class DependencyMissingError(RiskEngineError):
    """Raised when optional dependencies are required but unavailable."""
