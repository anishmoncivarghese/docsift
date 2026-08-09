import dataclasses

import pytest

from docsift.core.progress import ProgressEvent, emit


def test_emit_calls_the_callback_with_an_event():
    seen = []
    emit(seen.append, "convert", "converting report.pdf")
    assert seen == [ProgressEvent(phase="convert", message="converting report.pdf")]


def test_emit_is_a_no_op_when_callback_is_none():
    emit(None, "convert", "converting report.pdf")


def test_emit_swallows_callback_exceptions():
    def explode(event):
        raise RuntimeError("renderer is broken")

    emit(explode, "convert", "converting report.pdf")


def test_progress_event_is_frozen():
    event = ProgressEvent(phase="convert", message="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.phase = "other"
