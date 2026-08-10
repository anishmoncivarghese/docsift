import os
from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import Chunk, ConversionWarning, EngineOutput
from docsift.core.options import ChunkOptions, ConversionOptions
from docsift.core.progress import ProgressCallback, emit
from docsift.engines.base import ConversionEngine


def models_are_cached() -> bool:
    """True when docling's models look present on disk.

    Filesystem-only on purpose: it must answer before docling is imported, and
    must work in a test run where docling is not installed at all. When the
    answer is uncertain -- an unreadable home directory, say -- it returns True
    so the caller stays quiet. A false "downloading 1 GB" on every warm run
    would be a worse defect than the silence this is helping to fix.
    """
    hf_home = os.environ.get("HF_HOME")
    hub = Path(hf_home) / "hub" if hf_home else Path.home() / ".cache" / "huggingface" / "hub"
    for candidate in (hub, Path.home() / ".cache" / "docling"):
        try:
            if candidate.is_dir() and any(candidate.iterdir()):
                return True
        except OSError:
            return True  # cannot tell; stay quiet
    return False


def unused_cuda_warning() -> ConversionWarning | None:
    """Flag a CUDA build of PyTorch on a machine with no usable GPU.

    On Linux, `pip install docsift[docling]` resolves to the CUDA build --
    around 3.7 GB of nvidia wheels that a CPU-only machine never loads. No
    published wheel can prevent that: the CPU builds live on a separate index,
    and package metadata cannot redirect an installer. Saying so once, at the
    point the cost is actually paid, is the only thing that reaches someone who
    installed without reading the README.

    Returns None whenever the answer is not clearly yes, including any torch
    that does not look the way we expect.
    """
    try:
        import torch

        if torch.version.cuda is None or torch.cuda.is_available():
            return None
    except Exception:  # noqa: BLE001 - an advisory note must never break a run
        return None
    return ConversionWarning(
        code="unused_cuda_build",
        message=(
            "PyTorch was installed with CUDA support but no usable GPU was found; "
            "roughly 3.7 GB of that install is unused. Reinstall with "
            "'uv tool install --torch-backend auto' to drop it."
        ),
    )


class DoclingEngine(ConversionEngine):
    """Adapter for IBM docling. Imports stay lazy; first run downloads models."""

    name = "docling"

    @classmethod
    def is_available(cls) -> bool:
        try:
            return util.find_spec("docling") is not None
        except (ImportError, ValueError):
            # find_spec raises ValueError if a module named "docling" is already
            # present in sys.modules without a __spec__ (e.g. a test double).
            return False

    @classmethod
    def version(cls) -> str:
        if not cls.is_available():
            return "unknown"
        return metadata.version("docling")

    def convert(
        self,
        path: Path,
        options: ConversionOptions | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> EngineOutput:
        emit(on_progress, "engine_load", "loading docling (this imports PyTorch)")
        if not models_are_cached():
            emit(
                on_progress,
                "model_download",
                "first run: downloading layout and table models (~1 GB). This happens once.",
            )
        from docling.document_converter import DocumentConverter

        chunk_options = options.chunk if options else ChunkOptions()
        emit(on_progress, "convert", f"converting {path.name}")
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
        # Checked after the conversion, not before: torch is already imported by
        # then, so this costs nothing, and the note lands next to the wait it
        # explains.
        cuda_note = unused_cuda_warning()
        if cuda_note is not None:
            warnings = [*warnings, cuda_note]
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
            engine_version=self.version(),
        )

    def _chunk(self, document: object, chunk_options: ChunkOptions):
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
