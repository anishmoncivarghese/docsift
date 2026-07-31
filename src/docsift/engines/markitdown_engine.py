from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine


class MarkItDownEngine(ConversionEngine):
    """Adapter for microsoft/markitdown. Imports stay lazy."""

    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return util.find_spec("markitdown") is not None

    def convert(self, path: Path) -> EngineOutput:
        from markitdown import MarkItDown

        try:
            result = MarkItDown().convert(str(path))
        except Exception as exc:
            raise ConversionFailedError(f"markitdown failed on '{path.name}': {exc}") from exc
        return EngineOutput(
            markdown=result.text_content or "",
            title=getattr(result, "title", None),
            engine_version=metadata.version("markitdown"),
        )
