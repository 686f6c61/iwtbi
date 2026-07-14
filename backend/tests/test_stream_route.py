"""Tests del streaming SSE."""

import pytest

from app.routes.stream import _read_next_sse_frame
from app.store.job_store import JobStore


@pytest.mark.asyncio
async def test_read_next_sse_frame_marks_terminal_event():
    store = JobStore()
    job = store.create("https://github.com/octo/demo")
    await store.emit_event(job.job_id, "analysis_error", {"message": "boom"})

    frame, is_terminal = await _read_next_sse_frame(store, job.job_id)

    assert is_terminal is True
    assert "event: analysis_error" in frame
    assert '"message": "boom"' in frame


@pytest.mark.asyncio
async def test_read_next_sse_frame_returns_ping_on_timeout(monkeypatch):
    store = JobStore()
    job = store.create("https://github.com/octo/demo")
    monkeypatch.setattr("app.routes.stream._SSE_PING_INTERVAL", 0.01)

    frame, is_terminal = await _read_next_sse_frame(store, job.job_id)

    assert frame == ": ping\n\n"
    assert is_terminal is False
