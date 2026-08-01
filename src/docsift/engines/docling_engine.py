from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine


class DoclingEngine(ConversionEngine):
    """Adapter for IBM docling. Imports stay lazy; first run downloads models."""

    name = "docling"

    @classmethod
    def is_available(cls) -> bool:
        return util.find_spec("docling") is not None

    def convert(self, path: Path) -> EngineOutput:
        from docling.document_converter import DocumentConverter

        try:
            result = DocumentConverter().convert(str(path))
            document = result.document
            markdown = document.export_to_markdown()
        except Exception as exc:
            # Exception text can quote document content; expose only the type name.
            raise ConversionFailedError(
                f"docling failed on '{path.name}': {type(exc).__name__}"
            ) from exc
        page_count = len(document.pages) if getattr(document, "pages", None) else None
        title = None
        for item in getattr(document, "texts", []):
            if type(item).__name__ == "TitleItem":
                title = getattr(item, "text", None)
                break
        return EngineOutput(
            markdown=markdown,
            title=title,
            page_count=page_count,
            engine_version=metadata.version("docling"),
        )
