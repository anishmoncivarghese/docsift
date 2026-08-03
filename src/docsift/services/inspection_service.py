from pathlib import Path

from docsift import __version__
from docsift.core.exceptions import EngineNotAvailableError
from docsift.core.models import InspectionResult
from docsift.core.options import ConversionOptions
from docsift.engines.registry import get_engine
from docsift.engines.router import select_engine_name
from docsift.services.conversion_service import build_source_metadata
from docsift.storage.cache import cache_key, load_cached


def inspect_document(
    path: Path,
    engine: str = "auto",
    options: ConversionOptions | None = None,
) -> InspectionResult:
    """Report routing, identity and cache status for `path`. Never converts."""
    options = options or ConversionOptions()
    path = Path(path)
    source = build_source_metadata(path)
    engine_name, reason = select_engine_name(path, engine)

    engine_available = True
    engine_version = "unknown"
    cached = False
    try:
        engine_impl = get_engine(engine_name)
    except EngineNotAvailableError:
        engine_available = False
    else:
        engine_version = engine_impl.version()
        key = cache_key(source.sha256, engine_name, engine_version, __version__, options)
        cached = load_cached(key) is not None

    return InspectionResult(
        source=source,
        document_id=f"doc_{source.sha256[:12]}",
        engine=engine_name,
        selection_reason=reason,
        engine_available=engine_available,
        engine_version=engine_version,
        cached=cached,
    )
