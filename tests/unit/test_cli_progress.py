from typer.testing import CliRunner

from docsift.cli.main import app
from docsift.cli.progress import progress_reporter
from docsift.core.progress import ProgressEvent

runner = CliRunner()


def test_non_tty_reporter_writes_plain_lines_to_stderr(capsys):
    with progress_reporter(enabled=True) as report:
        report(ProgressEvent(phase="convert", message="converting note.csv"))
    captured = capsys.readouterr()
    assert "converting note.csv" in captured.err
    assert "\x1b[" not in captured.err
    assert captured.out == ""


def test_disabled_reporter_yields_none_and_prints_nothing(capsys):
    with progress_reporter(enabled=False) as report:
        assert report is None
    assert capsys.readouterr().err == ""


def test_sticky_phase_is_printed_and_not_only_spun(capsys):
    with progress_reporter(enabled=True) as report:
        report(
            ProgressEvent(
                phase="model_download",
                message="first run: downloading layout and table models (~1 GB).",
            )
        )
        report(ProgressEvent(phase="convert", message="converting note.csv"))
    assert "downloading layout and table models" in capsys.readouterr().err


def test_convert_still_succeeds_with_progress_enabled(tmp_path):
    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["convert", str(source), "--output", str(tmp_path / "out"), "--no-cache"],
    )
    assert result.exit_code == 0, result.output
    assert "document_id:" in result.output


def test_quiet_runs_clean(tmp_path):
    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["convert", str(source), "--output", str(tmp_path / "out"), "--quiet", "--no-cache"],
    )
    assert result.exit_code == 0, result.output
    assert "checking cache" not in result.output
