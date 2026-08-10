"""What the terminal actually shows during a real conversion.

The unit tests around `docsift.core.quiet` check logger levels and filters --
implementation detail. They would all have passed while a 34-page PDF wrote 113
lines to stderr, because the noisiest library configures its logger part-way
through the conversion. Only running the real thing catches that, and only
against a document that reaches the OCR path.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("docling")

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent.parent / "fixtures"

# Every line DocSift itself is allowed to write to stderr during a conversion.
# Progress phases plus its own warnings; anything else is a library talking over
# it. Matched as prefixes, since phases carry a filename and warnings a message.
ALLOWED_STDERR_PREFIXES = (
    "checking cache",
    "loading docling",
    "loading markitdown",
    "first run: downloading",
    "converting ",
    "chunking",
    "writing output",
    "warning: ",
)


def _cli() -> list[str]:
    """How to invoke the CLI as a subprocess.

    Not `-m docsift.cli.main`: that module has no __main__ guard, so it imports
    and exits 0 with no output -- which silently turns every assertion here into
    a pass against an empty string.
    """
    script = Path(sys.executable).with_name("docsift")
    if script.exists():
        return [str(script)]
    return [sys.executable, "-c", "from docsift.cli.main import app; app()"]


def _convert(pdf: Path, tmp_path: Path, *flags: str, verbose: bool = False):
    env = dict(os.environ)
    env.pop("DOCSIFT_VERBOSE", None)
    if verbose:
        env["DOCSIFT_VERBOSE"] = "1"
    return subprocess.run(
        [
            *_cli(),
            "convert",
            str(pdf),
            "--no-cache",
            "--output",
            str(tmp_path / "out"),
            *flags,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )


@pytest.mark.parametrize("fixture", ["scanned.pdf", "multipage.pdf"])
def test_stderr_carries_nothing_but_docsifts_own_lines(fixture, tmp_path):
    """scanned.pdf is the one that matters: it forces docling to run OCR."""
    result = _convert(FIXTURES / fixture, tmp_path)
    assert result.returncode == 0, result.stderr
    # Guard against a vacuous pass: no output at all would satisfy every
    # assertion below without the CLI having done anything.
    assert result.stdout.strip(), "the CLI produced no output; it did not run"

    intruders = [
        line
        for line in result.stderr.splitlines()
        if line.strip() and not line.startswith(ALLOWED_STDERR_PREFIXES)
    ]
    assert not intruders, (
        f"{len(intruders)} line(s) of engine logging reached the terminal:\n"
        + "\n".join(intruders[:10])
    )


def test_stdout_stays_machine_readable(tmp_path):
    """Whatever the engines print, stdout is the result block and nothing else."""
    result = _convert(FIXTURES / "scanned.pdf", tmp_path)
    assert result.returncode == 0, result.stderr

    keys = [line.split(":", 1)[0] for line in result.stdout.splitlines() if line.strip()]
    assert keys == [
        "document_id",
        "engine",
        "estimated_tokens",
        "chunks",
        "markdown",
        "result_json",
    ], result.stdout


def test_verbose_gives_the_engine_logging_back(tmp_path):
    """A silence you cannot undo is its own defect: bug reports need the detail."""
    quiet = _convert(FIXTURES / "scanned.pdf", tmp_path)
    loud = _convert(FIXTURES / "scanned.pdf", tmp_path, verbose=True)

    assert loud.returncode == 0, loud.stderr
    assert len(loud.stderr.splitlines()) > len(quiet.stderr.splitlines())
    assert "RapidOCR" in loud.stderr
