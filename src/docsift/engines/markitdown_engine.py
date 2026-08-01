from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import EngineOutput
from docsift.core.options import ConversionOptions
from docsift.engines.base import ConversionEngine


class MarkItDownEngine(ConversionEngine):
    """Adapter for microsoft/markitdown. Imports stay lazy."""

    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return util.find_spec("markitdown") is not None

    @classmethod
    def version(cls) -> str:
        if not cls.is_available():
            return "unknown"
        return metadata.version("markitdown")

    def convert(self, path: Path, options: ConversionOptions | None = None) -> EngineOutput:
        from markitdown import MarkItDown

        try:
            result = MarkItDown().convert(str(path))
        except Exception as exc:
            # Exception text can quote document content; expose only the type name.
            raise ConversionFailedError(
                f"markitdown failed on '{path.name}': {type(exc).__name__}"
            ) from exc
        return EngineOutput(
            markdown=result.text_content or "",
            title=getattr(result, "title", None),
            engine_version=metadata.version("markitdown"),
        )
