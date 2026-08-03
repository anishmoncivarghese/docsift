import hashlib
import os
import tempfile
from pathlib import Path

from docsift.core.models import ConversionResult
from docsift.core.options import ConversionOptions


def cache_dir() -> Path:
    override = os.environ.get("DOCSIFT_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".cache" / "docsift"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_key(
    source_sha256: str,
    engine_name: str,
    engine_version: str,
    docsift_version: str,
    options: ConversionOptions,
) -> str:
    material = "\n".join(
        [source_sha256, engine_name, engine_version, docsift_version, options.model_dump_json()]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def load_cached(key: str) -> ConversionResult | None:
    entry = cache_dir() / f"{key}.json"
    if not entry.is_file():
        return None
    try:
        return ConversionResult.model_validate_json(entry.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def store_cached(key: str, result: ConversionResult) -> None:
    target = cache_dir() / f"{key}.json"
    handle = tempfile.NamedTemporaryFile(
        "w", dir=target.parent, suffix=".tmp", delete=False, encoding="utf-8"
    )
    try:
        handle.write(result.model_dump_json(indent=2))
        handle.close()
        os.replace(handle.name, target)
    except OSError:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise


def cache_entries() -> list[Path]:
    """Every stored conversion result."""
    return sorted(cache_dir().glob("*.json"))


def cache_stats() -> tuple[int, int]:
    """(number of cached results, total bytes on disk)."""
    entries = cache_entries()
    return len(entries), sum(entry.stat().st_size for entry in entries)


def clear_cache() -> int:
    """Delete every cached result. Returns how many were removed."""
    removed = 0
    for entry in cache_entries():
        try:
            entry.unlink()
        except OSError:
            continue
        removed += 1
    return removed
