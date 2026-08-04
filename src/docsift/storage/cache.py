import hashlib
import os
import re
import tempfile
from pathlib import Path

from docsift.core.models import ConversionResult
from docsift.core.options import ConversionOptions


def cache_dir(create: bool = True) -> Path:
    override = os.environ.get("DOCSIFT_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".cache" / "docsift"
    if create:
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


_ENTRY_NAME = re.compile(r"^[0-9a-f]{64}\.json$")


def cache_entries() -> list[Path]:
    """Every stored conversion result.

    Matched by DocSift's own `{sha256}.json` naming so that a cache directory
    shared with other files — `DOCSIFT_CACHE_DIR` is a bare env var and may
    point anywhere — never has unrelated files reported or deleted.
    """
    return sorted(
        entry
        for entry in cache_dir(create=False).glob("*.json")
        if _ENTRY_NAME.fullmatch(entry.name)
    )


def cache_stats() -> tuple[int, int]:
    """(number of cached results, total bytes on disk).

    Entries that vanish between the listing and the measurement — a concurrent
    `cache clear`, say — are skipped rather than crashing the command.
    """
    count = 0
    total = 0
    for entry in cache_entries():
        try:
            total += entry.stat().st_size
        except OSError:
            continue
        count += 1
    return count, total


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
