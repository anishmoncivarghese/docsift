from pathlib import Path

from docsift.core.config import Settings, get_settings


def test_defaults_when_no_env(monkeypatch):
    for name in (
        "DOCSIFT_DATA_DIR",
        "DOCSIFT_MAX_UPLOAD_BYTES",
        "DOCSIFT_JOB_WORKERS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.data_dir == Path.home() / ".local" / "share" / "docsift"
    assert settings.max_upload_bytes == 50 * 1024 * 1024
    assert settings.job_workers == 2


def test_env_overrides_are_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("DOCSIFT_JOB_WORKERS", "5")
    settings = get_settings()
    assert settings.data_dir == tmp_path / "data"
    assert settings.max_upload_bytes == 1024
    assert settings.job_workers == 5


def test_job_timeout_setting_was_removed_as_dead(monkeypatch):
    """DOCSIFT_JOB_TIMEOUT_SECONDS never enforced anything (Fix 4, M4 review):
    the field was modelled and read from the environment but nothing ever
    consulted it, so it looked like protection it didn't provide. Removed
    rather than wired up, since NFR-04's timeout is a real feature this
    milestone chose not to build yet -- see README's Known limitations."""
    monkeypatch.setenv("DOCSIFT_JOB_TIMEOUT_SECONDS", "30")
    settings = get_settings()
    assert not hasattr(settings, "job_timeout_seconds")


def test_get_settings_does_not_create_the_directory(monkeypatch, tmp_path):
    target = tmp_path / "never-created"
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(target))
    get_settings()
    assert not target.exists()
