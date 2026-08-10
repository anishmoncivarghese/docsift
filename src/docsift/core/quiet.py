"""Keep the engines' own logging out of the user's terminal.

Converting a 34-page PDF writes 113 lines to stderr, 107 of them from docling
and its model stack: torch dynamo graph-break notices, and one WARNING per page
saying OCR found no text -- which is the normal case for a born-digital PDF, not
a problem. It buries DocSift's own output, and it reads like a failure on a
conversion that succeeded.

None of it is silenced permanently: set DOCSIFT_VERBOSE=1 to get all of it back,
which is what a bug report needs.
"""

import logging
import os

# Every logger that writes to the terminal during a conversion. Children are
# covered by their parent unless they set a level of their own, which the torch
# subsystems do -- hence the explicit entries.
NOISY_LOGGERS = (
    "docling",
    "docling_core",
    "docling_ibm_models",
    "RapidOCR",
    "transformers",
    "torch",
    "torch._dynamo",
    "torch._inductor",
    "onnxruntime",
    "huggingface_hub",
    "filelock",
    "PIL",
)

# Must be set before the engine imports: these are read at import time.
QUIET_ENV = {
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",  # the "Loading weights" bar
    "TRANSFORMERS_VERBOSITY": "error",
    "TOKENIZERS_PARALLELISM": "false",  # otherwise it warns about forking
}

_TRUTHY_OFF = {"", "0", "false", "no", "off"}


class _MinLevel(logging.Filter):
    """Drop records below `level`, whatever the logger's level says.

    A filter rather than a level because rapidocr is imported lazily, part-way
    through the conversion, and its Logger sets its own level to INFO on the way
    in -- overwriting anything set beforehand. Filters survive that: they are
    attached to the logger and consulted inside Logger.handle().
    """

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.level


def engine_logs_wanted() -> bool:
    """True when the user has asked to see the engine's own output."""
    return os.environ.get("DOCSIFT_VERBOSE", "").strip().lower() not in _TRUTHY_OFF


def prepare_quiet_env() -> None:
    """Quiet the engine's import-time chatter. Call before importing it.

    Uses setdefault, so anything the user set explicitly wins.
    """
    if engine_logs_wanted():
        return
    for name, value in QUIET_ENV.items():
        os.environ.setdefault(name, value)


def silence_engine_loggers() -> None:
    """Hold the noisy loggers at ERROR for the rest of the process.

    Both a level and a filter. The level is enough for anything already
    imported; the filter is what holds when a library is imported later and
    sets its own level, which rapidocr does mid-conversion.
    """
    if engine_logs_wanted():
        return
    for name in NOISY_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.ERROR)
        if not any(isinstance(existing, _MinLevel) for existing in logger.filters):
            logger.addFilter(_MinLevel(logging.ERROR))
    _quiet_onnxruntime()


def _quiet_onnxruntime() -> None:
    """Turn down onnxruntime's C++ logger, which writes past Python entirely.

    On Linux it announces its PCI bus scan at WARNING on the way up -- native
    code writing to fd 2, so no logging filter can see it. The severity has to
    be set before any inference session is created, which means importing
    onnxruntime here rather than waiting for rapidocr to do it mid-conversion.
    The import is not wasted: this runs only on the docling path, which loads
    onnxruntime regardless.
    """
    try:
        import onnxruntime

        onnxruntime.set_default_logger_severity(3)  # 3 = error
    except Exception:  # noqa: BLE001 - absent, or a build without the setter
        pass
