import logging

from docsift.core.quiet import (
    NOISY_LOGGERS,
    engine_logs_wanted,
    prepare_quiet_env,
    silence_engine_loggers,
)


def test_quiet_by_default(monkeypatch):
    monkeypatch.delenv("DOCSIFT_VERBOSE", raising=False)
    assert engine_logs_wanted() is False


def test_verbose_when_asked(monkeypatch):
    monkeypatch.setenv("DOCSIFT_VERBOSE", "1")
    assert engine_logs_wanted() is True


def test_off_values_do_not_count_as_verbose(monkeypatch):
    for value in ("", "0", "false", "no", "off", "OFF"):
        monkeypatch.setenv("DOCSIFT_VERBOSE", value)
        assert engine_logs_wanted() is False, value


def test_prepare_quiet_env_sets_the_import_time_switches(monkeypatch):
    monkeypatch.delenv("DOCSIFT_VERBOSE", raising=False)
    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
    prepare_quiet_env()
    assert os_environ("HF_HUB_DISABLE_PROGRESS_BARS") == "1"


def test_prepare_quiet_env_respects_an_explicit_setting(monkeypatch):
    monkeypatch.delenv("DOCSIFT_VERBOSE", raising=False)
    monkeypatch.setenv("TRANSFORMERS_VERBOSITY", "debug")
    prepare_quiet_env()
    assert os_environ("TRANSFORMERS_VERBOSITY") == "debug"


def test_prepare_quiet_env_does_nothing_when_verbose(monkeypatch):
    monkeypatch.setenv("DOCSIFT_VERBOSE", "1")
    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
    prepare_quiet_env()
    assert os_environ("HF_HUB_DISABLE_PROGRESS_BARS") is None


def test_silence_engine_loggers_raises_every_noisy_logger(monkeypatch):
    monkeypatch.delenv("DOCSIFT_VERBOSE", raising=False)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)

    silence_engine_loggers()

    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.ERROR, name


def test_silence_engine_loggers_leaves_them_alone_when_verbose(monkeypatch):
    monkeypatch.setenv("DOCSIFT_VERBOSE", "1")
    logging.getLogger("RapidOCR").setLevel(logging.INFO)

    silence_engine_loggers()

    assert logging.getLogger("RapidOCR").level == logging.INFO


def os_environ(name):
    import os

    return os.environ.get(name)


def test_silence_survives_a_library_resetting_its_own_level(monkeypatch):
    """rapidocr sets its logger to INFO when it is imported mid-conversion."""
    monkeypatch.delenv("DOCSIFT_VERBOSE", raising=False)
    silence_engine_loggers()

    logger = logging.getLogger("RapidOCR")
    logger.setLevel(logging.INFO)  # what rapidocr does on import

    record = logger.makeRecord(
        "RapidOCR", logging.WARNING, __file__, 1, "text detection result is empty", (), None
    )
    assert not logger.filter(record)


def test_errors_still_get_through(monkeypatch):
    monkeypatch.delenv("DOCSIFT_VERBOSE", raising=False)
    silence_engine_loggers()

    logger = logging.getLogger("docling")
    record = logger.makeRecord(
        "docling", logging.ERROR, __file__, 1, "the conversion actually failed", (), None
    )
    assert logger.filter(record)


def test_filter_is_not_added_twice(monkeypatch):
    monkeypatch.delenv("DOCSIFT_VERBOSE", raising=False)
    silence_engine_loggers()
    silence_engine_loggers()
    assert len(logging.getLogger("RapidOCR").filters) == 1
