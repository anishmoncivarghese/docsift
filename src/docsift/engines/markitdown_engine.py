import re
from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import Chunk, EngineOutput
from docsift.core.options import ConversionOptions
from docsift.core.progress import ProgressCallback, emit
from docsift.engines.base import ConversionEngine

# MarkItDown marks slide boundaries its own way. The rest of the pipeline --
# the cleaner's furniture detection, the chunker's page attribution -- is built
# around `<!-- page: N -->`, so translate here, at the engine boundary, rather
# than teaching those modules a second vendor's format.
_SLIDE_MARKER = re.compile(r"^<!-- Slide number: (\d+) -->$", re.MULTILINE)


_PAGE_MARKER_LINE = re.compile(r"^<!-- page: \d+ -->$", re.MULTILINE)


def split_by_slide(markdown: str) -> list[str]:
    """Cut normalised Markdown into one segment per slide, marker included.

    Empty when there are no markers, which is how every non-presentation format
    keeps the ordinary whole-document chunker.
    """
    starts = [match.start() for match in _PAGE_MARKER_LINE.finditer(markdown)]
    if not starts:
        return []
    segments = [markdown[a:b] for a, b in zip(starts, starts[1:] + [len(markdown)], strict=True)]
    preamble = markdown[: starts[0]].strip()
    if preamble:
        # Content before the first marker is rare, but dropping it would lose
        # document text outright. It rides with the first slide.
        segments[0] = f"{preamble}\n\n{segments[0]}"
    return segments


_IMAGE_ONLY_LINE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$", re.MULTILINE)


def slide_chunks(markdown: str, options: ConversionOptions) -> list[Chunk]:
    """One chunk per slide, so an answer can name the slide it came from.

    A slide is a semantic unit in a way a page is not -- nobody thinks in terms
    of the second half of slide 14 -- and the token-budgeted chunker alone
    packs dozens of sparse slides into one chunk, which cites as "slides 1-55"
    and is no use to anyone. Each slide still goes through the ordinary chunker,
    so a slide too big for the budget is split the usual way.

    Image references are dropped first, when the caller wants them gone. Real
    decks put the picture above the title, and the chunker takes a chunk's
    section path from its first non-heading block -- so a leading image, whose
    heading path was captured before any heading existed, leaves every slide
    reported as untitled. The document-level cleaner removes these too, but too
    late: the chunk's metadata is already fixed by then.
    """
    from docsift.processing.chunker import chunk_markdown

    chunks: list[Chunk] = []
    for segment in split_by_slide(markdown):
        if options.clean.remove_image_refs:
            segment = _IMAGE_ONLY_LINE.sub("", segment)
        for chunk in chunk_markdown(segment, "slide", options.chunk):
            chunks.append(chunk.model_copy(update={"chunk_id": f"c{len(chunks):03d}"}))
    return chunks


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
        conversion_options = options or ConversionOptions()
        chunks = slide_chunks(markdown, conversion_options) if page_count is not None else None
        return EngineOutput(
            markdown=markdown,
            title=getattr(result, "title", None),
            page_count=page_count,
            chunks=chunks,
            engine_version=metadata.version("markitdown"),
        )
