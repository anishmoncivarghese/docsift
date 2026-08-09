from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from docsift.core.models import EngineOutput
from docsift.core.options import ConversionOptions
from docsift.core.progress import ProgressCallback


class ConversionEngine(ABC):
    """One document-conversion backend. Implementations keep their imports lazy."""

    name: ClassVar[str]

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """True when the engine's optional dependency is importable."""

    @classmethod
    def version(cls) -> str:
        """Installed engine package version; 'unknown' when unavailable."""
        return "unknown"

    @abstractmethod
    def convert(
        self,
        path: Path,
        options: ConversionOptions | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> EngineOutput:
        """Convert the file at `path`. Raises on failure; never returns None.

        `on_progress` is optional and advisory: implementations report phases
        through `docsift.core.progress.emit`, which ignores a None callback.
        """
