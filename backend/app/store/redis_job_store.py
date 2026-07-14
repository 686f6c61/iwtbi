"""
Store de jobs sobre Redis para separar API y worker.

Mantiene:
- jobs persistidos en hashes
- eventos SSE en listas por job
- cola de trabajo global en Redis
- tickets efímeros con TTL
"""

from __future__ import annotations

import asyncio
import json

import redis

from app.config import settings
from app.models.job import Job, JobStatus


class RedisJobStore:
    """Implementación de job store persistente usando Redis."""

    _TICKET_TTL_SECONDS = 300

    def __init__(self, redis_url: str | None = None, prefix: str = "iwtbi") -> None:
        self.backend_kind = "redis"
        self._redis = redis.Redis.from_url(
            redis_url or settings.redis_url,
            decode_responses=True,
        )
        self._prefix = prefix

    def _job_key(self, job_id: str) -> str:
        return f"{self._prefix}:job:{job_id}"

    def _events_key(self, job_id: str) -> str:
        return f"{self._prefix}:job:{job_id}:events"

    def _queue_key(self) -> str:
        return f"{self._prefix}:jobs:queue"

    def _ticket_key(self, ticket: str) -> str:
        return f"{self._prefix}:ticket:{ticket}"

    def create(
        self,
        repo_url: str,
        *,
        llm_profile_id: str = "default",
        provider_override: str | None = None,
        model_override: str | None = None,
        disable_fallback: bool = False,
        profile_label: str | None = None,
    ) -> Job:
        job = Job(
            repo_url=repo_url,
            llm_profile_id=llm_profile_id,
            provider_override=provider_override,
            model_override=model_override,
            disable_fallback=disable_fallback,
            profile_label=profile_label,
        )
        self._redis.hset(
            self._job_key(job.job_id),
            mapping={
                "job_id": job.job_id,
                "repo_url": job.repo_url,
                "llm_profile_id": job.llm_profile_id,
                "provider_override": job.provider_override or "",
                "model_override": job.model_override or "",
                "disable_fallback": "1" if job.disable_fallback else "0",
                "profile_label": job.profile_label or "",
                "status": job.status.value,
                "document": "",
                "error": "",
                "cancel_requested": "0",
            },
        )
        return job

    def get(self, job_id: str) -> Job | None:
        data = self._redis.hgetall(self._job_key(job_id))
        if not data:
            return None
        return Job(
            job_id=data["job_id"],
            repo_url=data["repo_url"],
            llm_profile_id=data.get("llm_profile_id") or "default",
            provider_override=data.get("provider_override") or None,
            model_override=data.get("model_override") or None,
            disable_fallback=data.get("disable_fallback") == "1",
            profile_label=data.get("profile_label") or None,
            status=JobStatus(data.get("status", JobStatus.PENDING.value)),
            document=data.get("document") or None,
            error=data.get("error") or None,
        )

    def update_status(self, job_id: str, status: JobStatus) -> None:
        self._redis.hset(self._job_key(job_id), mapping={"status": status.value})

    def set_document(self, job_id: str, document: str) -> None:
        self._redis.hset(
            self._job_key(job_id),
            mapping={"document": document, "status": JobStatus.COMPLETE.value},
        )

    def set_error(self, job_id: str, error: str) -> None:
        self._redis.hset(
            self._job_key(job_id),
            mapping={"error": error, "status": JobStatus.ERROR.value},
        )

    def set_task(self, job_id: str, task) -> None:
        """No-op: el worker vive en otro proceso."""
        return None

    def enqueue(self, job_id: str) -> None:
        self._redis.rpush(self._queue_key(), job_id)

    def pop_next_job(self, timeout: int = 5) -> str | None:
        try:
            result = self._redis.blpop(self._queue_key(), timeout=timeout)
        except redis.exceptions.TimeoutError:
            return None
        if not result:
            return None
        _, job_id = result
        return job_id

    def remove(self, job_id: str) -> None:
        self._redis.delete(self._job_key(job_id), self._events_key(job_id))

    def issue_ticket(self, *, client_ip: str, user_agent: str) -> str:
        import uuid

        ticket = str(uuid.uuid4())
        self._redis.setex(
            self._ticket_key(ticket),
            self._TICKET_TTL_SECONDS,
            json.dumps({"client_ip": client_ip, "user_agent": user_agent.strip()}),
        )
        return ticket

    def consume_ticket(self, ticket: str, *, client_ip: str, user_agent: str) -> bool:
        key = self._ticket_key(ticket)
        raw = self._redis.get(key)
        if not raw:
            return False
        record = json.loads(raw)
        if record.get("client_ip") != client_ip:
            return False
        if record.get("user_agent") != user_agent.strip():
            return False
        self._redis.delete(key)
        return True

    def request_cancel(self, job_id: str) -> None:
        self._redis.hset(self._job_key(job_id), mapping={"cancel_requested": "1"})

    def is_cancel_requested(self, job_id: str) -> bool:
        return self._redis.hget(self._job_key(job_id), "cancel_requested") == "1"

    async def emit_event(self, job_id: str, event_type: str, data: dict) -> None:
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        await asyncio.to_thread(self._redis.rpush, self._events_key(job_id), payload)

    async def read_next_event(self, job_id: str, timeout: float) -> dict | None:
        def _read() -> dict | None:
            try:
                result = self._redis.blpop(
                    self._events_key(job_id),
                    timeout=int(timeout),
                )
            except redis.exceptions.TimeoutError:
                return None
            if not result:
                return None
            _, payload = result
            return json.loads(payload)

        return await asyncio.to_thread(_read)

    def drain_events(self, job_id: str) -> None:
        self._redis.delete(self._events_key(job_id))
