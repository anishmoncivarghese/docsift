"""Terminal rendering for conversion progress.

Writes to stderr so `docsift convert x.pdf > out.txt` stays machine-readable,
and degrades to plain lines when stderr is not a terminal so CI logs stay
readable.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from docsift.core.progress import ProgressCallback, ProgressEvent

# Phases whose message must survive the rest of the run instead of being
# overwritten by the next spinner update.
STICKY_PHASES = frozenset({"model_download"})


@contextmanager
def progress_reporter(enabled: bool = True) -> Iterator[ProgressCallback | None]:
    """Yield a progress callback, or None when progress is switched off."""
    if not enabled:
        yield None
        return

    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    console = Console(stderr=True)

    if not console.is_terminal:

        def plain(event: ProgressEvent) -> None:
            console.print(event.message, highlight=False, markup=False)

        yield plain
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        # total=None keeps the bar indeterminate: docling exposes no page
        # callback, and a fake percentage would be worse than none.
        task_id = progress.add_task("starting", total=None)

        def update(event: ProgressEvent) -> None:
            if event.phase in STICKY_PHASES:
                progress.console.print(event.message, highlight=False, markup=False)
            progress.update(task_id, description=event.message)

        yield update
