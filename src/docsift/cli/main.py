from pathlib import Path

import typer

from docsift import __version__

app = typer.Typer(
    help="DocSift — convert documents once, give agents only what they need.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"docsift {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the DocSift version and exit.",
    ),
) -> None:
    """DocSift command-line interface."""


@app.command()
def convert(
    path: Path = typer.Argument(..., help="File to convert."),
    engine: str = typer.Option("auto", help="Engine: auto, docling, or markitdown."),
    output: Path = typer.Option(Path("output"), help="Directory for Markdown and JSON."),
) -> None:
    """Convert a document to clean Markdown plus a normalized JSON result."""
    from docsift.core.exceptions import DocSiftError
    from docsift.services.conversion_service import convert_document

    try:
        result = convert_document(path, engine=engine, output_dir=output)
    except DocSiftError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"document_id: {result.document_id}")
    typer.echo(f"engine: {result.conversion.engine} ({result.conversion.selection_reason})")
    typer.echo(f"estimated_tokens: {result.metrics.estimated_tokens}")
    typer.echo(f"markdown: {output / (path.stem + '.md')}")
    typer.echo(f"result_json: {output / (path.stem + '.docsift.json')}")
