import re
from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import EngineOutput
from docsift.core.options import ConversionOptions
from docsift.core.progress import ProgressCallback, emit
from docsift.engines.base import ConversionEngine

# MarkItDown marks slide boundaries its own way. The rest of the pipeline --
# the cleaner's furniture detection, the chunker's page attribution -- is built
# around `<!-- page: N -->`, so translate here, at the engine boundary, rather
# than teaching those modules a second vendor's format.
_SLIDE_MARKER = re.compile(r"^<!-- Slide number: (\d+) -->$", re.MULTILINE)


def normalize_slide_markers(markdown: str) -> tuple[str, int | None]:
    """Rewrite slide markers as page markers; return that and the slide count.

    Numbers are carried across untouched: a citation should match what the user
    sees in PowerPoint, not a recount. Returns None for the count when the
    document has no slide markers at all, which is every non-presentation
    format and any deck an older MarkItDown produced.
    """
    numbers = [int(match.group(1)) for match in _SLIDE_MARKER.finditer(markdown)]
    if not numbers:
        return markdown, None
    return _SLIDE_MARKER.sub(r"<!-- page: \1 -->", markdown), max(numbers)


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

    def convert(
        self,
        path: Path,
        options: ConversionOptions | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> EngineOutput:
        emit(on_progress, "engine_load", "loading markitdown")
        from markitdown import MarkItDown

        emit(on_progress, "convert", f"converting {path.name}")
        try:
            result = MarkItDown().convert(str(path))
        except Exception as exc:
            # Exception text can quote document content; expose only the type name.
            raise ConversionFailedError(
                f"markitdown failed on '{path.name}': {type(exc).__name__}"
            ) from exc
        markdown, page_count = normalize_slide_markers(result.text_content or "")
        return EngineOutput(
            markdown=markdown,
            title=getattr(result, "title", None),
            page_count=page_count,
            engine_version=metadata.version("markitdown"),
        )
