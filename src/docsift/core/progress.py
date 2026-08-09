"""Progress reporting for long conversions.

A cold PDF conversion spends minutes inside one opaque engine call. These
events let a front end say what is happening; every consumer is optional and
a front end that breaks must never break a conversion.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressEvent:
    """One phase transition during a conversion."""

    phase: str
    """Machine-readable key, e.g. 'engine_load'. Stable; front ends may match on it."""

    message: str
    """Human-readable text for display."""


ProgressCallback = Callable[[ProgressEvent], None]


def emit(callback: ProgressCallback | None, phase: str, message: str) -> None:
    """Report a phase. Never raises: a broken renderer must not fail a conversion."""
    if callback is None:
        return
    try:
        callback(ProgressEvent(phase=phase, message=message))
    except Exception:  # noqa: BLE001 - progress is decoration, never a failure mode
        pass
