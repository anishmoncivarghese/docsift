class DocSiftError(Exception):
    """Base class for all DocSift errors."""


class UnsupportedFileError(DocSiftError):
    """The input file is missing, empty, too large, or of an unsupported type."""


class EngineNotAvailableError(DocSiftError):
    """The requested conversion engine is unknown or not installed."""


class ConversionFailedError(DocSiftError):
    """The engine raised while converting the document."""


class ServiceUnavailableError(DocSiftError):
    """The service is shutting down and cannot accept new work."""
