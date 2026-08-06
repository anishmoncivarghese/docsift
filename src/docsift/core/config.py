import os
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class Settings(BaseModel):
    """Runtime settings for the DocSift service.

    `data_dir` holds the service's records — the SQLite database and stored
    artifacts. It is deliberately separate from the conversion cache
    (`DOCSIFT_CACHE_DIR`), which is disposable.
    """

    data_dir: Path
    max_upload_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES, ge=1)
    job_workers: int = Field(default=2, ge=1)
    max_pending_jobs: int = Field(default=32, ge=1)
    api_key: str | None = None


def _positive_int_env(name: str, default: int) -> int:
    """Read `name` as a positive int, or fall back to `default` when unset.

    Raises a ValueError naming the offending variable -- a bare
    "invalid literal for int()" doesn't say which of several env vars was
    misconfigured, and Pydantic's own ValidationError names the model field,
    not the environment variable a deployer would actually need to fix.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer; got {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be at least 1; got {value}")
    return value


def get_settings() -> Settings:
    """Read settings from the environment. Called per use, never cached at import."""
    override = os.environ.get("DOCSIFT_DATA_DIR")
    data_dir = Path(override) if override else Path.home() / ".local" / "share" / "docsift"
    return Settings(
        data_dir=data_dir,
        max_upload_bytes=_positive_int_env("DOCSIFT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
        job_workers=_positive_int_env("DOCSIFT_JOB_WORKERS", 2),
        max_pending_jobs=_positive_int_env("DOCSIFT_MAX_PENDING_JOBS", 32),
        # HTTP strips whitespace from header values, so a trailing space in
        # the env var would otherwise lock the service out with no
        # diagnostic: the configured key could never match any header a
        # client actually sends.
        api_key=(os.environ.get("DOCSIFT_API_KEY") or "").strip() or None,
    )
