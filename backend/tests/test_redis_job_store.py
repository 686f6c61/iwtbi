"""Tests de tolerancia a timeouts del store Redis."""

import redis
import pytest

from app.store.redis_job_store import RedisJobStore


class _TimeoutRedis:
    def blpop(self, *_args, **_kwargs):
        raise redis.exceptions.TimeoutError("Timeout reading from socket")


def _store_with(fake_redis) -> RedisJobStore:
    store = RedisJobStore.__new__(RedisJobStore)
    store.backend_kind = "redis"
    store._redis = fake_redis
    store._prefix = "test"
    return store


def test_pop_next_job_treats_redis_timeout_as_empty_queue():
    store = _store_with(_TimeoutRedis())

    assert store.pop_next_job(timeout=1) is None


@pytest.mark.asyncio
async def test_read_next_event_treats_redis_timeout_as_no_event():
    store = _store_with(_TimeoutRedis())

    assert await store.read_next_event("job-1", timeout=1) is None
