from __future__ import annotations

import pytest

from filewatch.models import FileEvent
from filewatch.templates import render, render_argv


def _event() -> FileEvent:
    return FileEvent(
        id="evt_1",
        ts="2026-01-01T00:00:00Z",
        watch_id="inbox",
        type="moved",
        path="/tmp/new.md",
        old_path="/tmp/old.md",
        is_dir=False,
    )


def test_render_known_variables() -> None:
    event = _event()
    text = render("{{type}} {{filename}} {{old_path}} {{rule}}", event, {"rule": "docs"})
    assert text == "moved new.md /tmp/old.md docs"
    assert "moved" in render("{{json}}", event)
    argv = render_argv(["echo", "{{path}}"], event)
    assert argv == ["echo", "/tmp/new.md"]


def test_render_unknown_variable() -> None:
    with pytest.raises(KeyError, match="unknown template variable"):
        render("{{nope}}", _event())
