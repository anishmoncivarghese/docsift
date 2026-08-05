from pathlib import Path

import typer

from docsift import __version__

app = typer.Typer(
    help="DocSift — convert documents once, give agents only what they need.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
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
    max_tokens: int = typer.Option(1000, help="Maximum tokens per chunk."),
    overlap: int = typer.Option(
        100,
        help="Token overlap between chunks (ignored when the engine supplies its own chunks).",
    ),
    keep_image_refs: bool = typer.Option(
        False, "--keep-image-refs", help="Keep image references in the Markdown."
    ),
    keep_furniture: bool = typer.Option(
        False, "--keep-furniture", help="Keep repeated header/footer lines."
    ),
    furniture_min_repeats: int = typer.Option(
        3, help="How many times a line must repeat to count as header/footer furniture."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Convert even if a cached result exists."
    ),
) -> None:
    """Convert a document to clean Markdown plus a normalized JSON result."""
    from docsift.core.exceptions import DocSiftError
    from docsift.core.options import ChunkOptions, CleanOptions, ConversionOptions
    from docsift.services.conversion_service import convert_document

    options = ConversionOptions(
        clean=CleanOptions(
            remove_image_refs=not keep_image_refs,
            remove_furniture=not keep_furniture,
            furniture_min_repeats=furniture_min_repeats,
        ),
        chunk=ChunkOptions(max_tokens=max_tokens, overlap_tokens=overlap),
    )

    try:
        result = convert_document(
            path, engine=engine, output_dir=output, options=options, use_cache=not no_cache
        )
    except DocSiftError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.secho(
            f"error: unexpected failure: {type(exc).__name__}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1) from exc
    typer.echo(f"document_id: {result.document_id}")
    typer.echo(f"engine: {result.conversion.engine} ({result.conversion.selection_reason})")
    typer.echo(f"estimated_tokens: {result.metrics.estimated_tokens}")
    typer.echo(f"chunks: {len(result.chunks)}")
    typer.echo(f"markdown: {output / (path.stem + '.md')}")
    typer.echo(f"result_json: {output / (path.stem + '.docsift.json')}")
    for warning in result.warnings:
        typer.secho(f"warning: {warning.code}: {warning.message}", fg=typer.colors.YELLOW, err=True)


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="File to inspect."),
    engine: str = typer.Option("auto", help="Engine: auto, docling, or markitdown."),
) -> None:
    """Show how DocSift would handle a file, without converting it."""
    from docsift.core.exceptions import DocSiftError
    from docsift.services.inspection_service import inspect_document

    try:
        result = inspect_document(path, engine=engine)
    except DocSiftError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.secho(
            f"error: unexpected failure: {type(exc).__name__}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1) from exc
    typer.echo(f"document_id: {result.document_id}")
    typer.echo(f"filename: {result.source.filename}")
    typer.echo(f"media_type: {result.source.media_type}")
    typer.echo(f"size_bytes: {result.source.size_bytes}")
    typer.echo(f"sha256: {result.source.sha256}")
    typer.echo(f"engine: {result.engine} ({result.selection_reason})")
    typer.echo(f"engine_available: {result.engine_available}")
    typer.echo(f"engine_version: {result.engine_version}")
    typer.echo(f"cached: {result.cached}")


@app.command()
def compare(
    path: Path = typer.Argument(..., help="File to run through every engine."),
    output: Path = typer.Option(Path("output"), help="Directory for per-engine and report files."),
) -> None:
    """Convert with every engine and write a comparison report."""
    from docsift.core.exceptions import DocSiftError
    from docsift.services.comparison_service import compare_document

    try:
        comparison = compare_document(path, output_dir=output)
    except DocSiftError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.secho(
            f"error: unexpected failure: {type(exc).__name__}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1) from exc

    for run in comparison.runs:
        if run.success:
            typer.echo(
                f"{run.engine}: ok (duration_ms={run.duration_ms}, "
                f"estimated_tokens={run.estimated_tokens})"
            )
        else:
            typer.echo(f"{run.engine}: failed ({run.error})")
    typer.echo(f"comparison_json: {output / (path.stem + '.compare.json')}")
    typer.echo(f"comparison_report: {output / (path.stem + '.compare.md')}")
    if not any(run.success for run in comparison.runs):
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Interface to bind."),
    port: int = typer.Option(8000, help="Port to listen on."),
    reload: bool = typer.Option(False, "--reload", help="Reload on code changes."),
) -> None:
    """Run the DocSift HTTP API."""
    try:
        import uvicorn
    except ImportError as exc:
        typer.secho(
            "error: the API extra is not installed; install it with: pip install 'docsift[api]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    uvicorn.run("docsift.api.app:app", host=host, port=port, reload=reload)


cache_app = typer.Typer(help="Inspect and clear the conversion cache.", no_args_is_help=True)
app.add_typer(cache_app, name="cache")


@cache_app.command("info")
def cache_info() -> None:
    """Show where the cache lives and how much space it uses."""
    from docsift.storage.cache import cache_dir, cache_stats

    count, size = cache_stats()
    typer.echo(f"location: {cache_dir(create=False)}")
    typer.echo(f"entries: {count}")
    typer.echo(f"bytes: {size}")


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete every cached conversion result."""
    from docsift.storage.cache import clear_cache

    typer.echo(f"removed {clear_cache()} cached results")
