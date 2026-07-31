from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from docsift.core.models import EngineOutput


class ConversionEngine(ABC):
    """One document-conversion backend. Implementations keep their imports lazy."""

    name: ClassVar[str]

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """True when the engine's optional dependency is importable."""

    @abstractmethod
    def convert(self, path: Path) -> EngineOutput:
        """Convert the file at `path`. Raises on failure; never returns None."""
