"""Tests del streaming SSE."""

import asyncio
from unittest.mock import patch

import pytest

from app.models.job import JobStatus
from app.routes.stream import _cancel_pipeline_if_no_emails, _read_next_sse_frame
from app.store.job_store import JobStore


@pytest.mark.asyncio
async def test_read_next_sse_frame_marks_terminal_event():
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put({"type": "analysis_error", "data": {"message": "boom"}})

    frame, is_terminal = await _read_next_sse_frame(queue)

    assert is_terminal is True
    assert "event: analysis_error" in frame
    assert '"message": "boom"' in frame


def test_cancel_pipeline_keeps_job_alive_when_notifications_exist():
    store = JobStore()
    job = store.create("https://github.com/octo/demo")

    class DummyTask:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    task = DummyTask()
    store.set_task(job.job_id, task)
    store.update_status(job.job_id, JobStatus.ANALYZING)

    with patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[{"email": "test@example.com"}]):
        _cancel_pipeline_if_no_emails(store, job.job_id)

    assert store.get(job.job_id) is not None
    assert task.cancelled is False


def test_cancel_pipeline_removes_job_when_notifications_do_not_exist():
    store = JobStore()
    job = store.create("https://github.com/octo/demo")

    class DummyTask:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    task = DummyTask()
    store.set_task(job.job_id, task)
    store.update_status(job.job_id, JobStatus.ANALYZING)

    with patch("app.database.notifications_repo.NotificationsRepo.find_by_job", return_value=[]):
        _cancel_pipeline_if_no_emails(store, job.job_id)

    assert store.get(job.job_id) is None
    assert task.cancelled is True
