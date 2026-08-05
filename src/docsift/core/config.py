import os
from pathlib import Path

from pydantic import BaseModel

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class Settings(BaseModel):
    """Runtime settings for the DocSift service.

    `data_dir` holds the service's records — the SQLite database and stored
    artifacts. It is deliberately separate from the conversion cache
    (`DOCSIFT_CACHE_DIR`), which is disposable.
    """

    data_dir: Path
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    job_workers: int = 2
    max_pending_jobs: int = 32


def get_settings() -> Settings:
    """Read settings from the environment. Called per use, never cached at import."""
    override = os.environ.get("DOCSIFT_DATA_DIR")
    data_dir = Path(override) if override else Path.home() / ".local" / "share" / "docsift"
    return Settings(
        data_dir=data_dir,
        max_upload_bytes=int(os.environ.get("DOCSIFT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)),
        job_workers=int(os.environ.get("DOCSIFT_JOB_WORKERS", 2)),
        max_pending_jobs=int(os.environ.get("DOCSIFT_MAX_PENDING_JOBS", 32)),
    )
