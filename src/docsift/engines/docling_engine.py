from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import Chunk, ConversionWarning, EngineOutput
from docsift.core.options import ChunkOptions, ConversionOptions
from docsift.engines.base import ConversionEngine


class DoclingEngine(ConversionEngine):
    """Adapter for IBM docling. Imports stay lazy; first run downloads models."""

    name = "docling"

    @classmethod
    def is_available(cls) -> bool:
        return util.find_spec("docling") is not None

    @classmethod
    def version(cls) -> str:
        if not cls.is_available():
            return "unknown"
        return metadata.version("docling")

    def convert(self, path: Path, options: ConversionOptions | None = None) -> EngineOutput:
        from docling.document_converter import DocumentConverter

        chunk_options = options.chunk if options else ChunkOptions()
        try:
            result = DocumentConverter().convert(str(path))
            document = result.document
            try:
                markdown = document.export_to_markdown(page_break_placeholder="<!-- page-break -->")
            except TypeError:  # older docling without the keyword
                markdown = document.export_to_markdown()
        except Exception as exc:
            # Exception text can quote document content; expose only the type name.
            raise ConversionFailedError(
                f"docling failed on '{path.name}': {type(exc).__name__}"
            ) from exc
        chunks, warnings = self._chunk(document, chunk_options)
        title = None
        for item in getattr(document, "texts", []):
            if type(item).__name__ == "TitleItem":
                title = getattr(item, "text", None)
                break
        page_count = len(document.pages) if getattr(document, "pages", None) else None
        return EngineOutput(
            markdown=markdown,
            title=title,
            page_count=page_count,
            chunks=chunks,
            warnings=warnings,
            engine_version=metadata.version("docling"),
        )

    def _chunk(self, document, chunk_options):
        """Map docling HybridChunker output to neutral Chunk models; degrade gracefully."""
        from docsift.processing.token_estimator import estimate_tokens

        try:
            import tiktoken
            from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
            from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer

            tokenizer = OpenAITokenizer(
                tokenizer=tiktoken.get_encoding("o200k_base"),
                max_tokens=chunk_options.max_tokens,
            )
            chunker = HybridChunker(tokenizer=tokenizer)
            chunks: list[Chunk] = []
            for index, docling_chunk in enumerate(chunker.chunk(dl_doc=document)):
                text = chunker.contextualize(chunk=docling_chunk)
                headings = list(getattr(docling_chunk.meta, "headings", None) or [])
                pages = sorted(
                    {
                        prov.page_no
                        for item in getattr(docling_chunk.meta, "doc_items", []) or []
                        for prov in getattr(item, "prov", []) or []
                    }
                )
                chunks.append(
                    Chunk(
                        chunk_id=f"c{index:03d}",
                        text=text,
                        estimated_tokens=estimate_tokens(text),
                        section_path=headings,
                        pages=pages,
                    )
                )
            return chunks, []
        except Exception as exc:
            return None, [
                ConversionWarning(
                    code="docling_chunker_unavailable",
                    message=(
                        "HybridChunker unavailable "
                        f"({type(exc).__name__}); markdown chunker will be used"
                    ),
                )
            ]
