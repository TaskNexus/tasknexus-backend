import json
import os
from functools import lru_cache
from typing import Any

import redis
from django.conf import settings

STREAM_KEY = os.environ.get("AGENT_DISPATCH_STREAM_KEY", "agent_dispatch_stream")
GROUP_NAME = os.environ.get("AGENT_DISPATCH_GROUP", "agent_dispatchers")
MAX_STREAM_LEN = int(os.environ.get("AGENT_DISPATCH_MAXLEN", "10000"))
MAX_RETRIES = int(os.environ.get("AGENT_DISPATCH_MAX_RETRIES", "5"))
BACKOFF_BASE_SECONDS = float(os.environ.get("AGENT_DISPATCH_BACKOFF_BASE", "0.5"))
BACKOFF_MAX_SECONDS = float(os.environ.get("AGENT_DISPATCH_BACKOFF_MAX", "10"))


def _resolve_redis_url() -> str:
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        return redis_url

    hosts = settings.CHANNEL_LAYERS.get("default", {}).get("CONFIG", {}).get("hosts", [])
    if hosts:
        first = hosts[0]
        if isinstance(first, str):
            return first
        if isinstance(first, (tuple, list)) and len(first) >= 2:
            host, port = first[0], first[1]
            return f"redis://{host}:{port}/0"

    return "redis://redis:6379/3"


@lru_cache(maxsize=1)
def _sync_redis() -> redis.Redis:
    return redis.Redis.from_url(_resolve_redis_url(), decode_responses=True)


def _publish_event(event_type: str, task_id: int, agent_id: int, payload: dict[str, Any], attempt: int = 0) -> str:
    fields = {
        "event_type": event_type,
        "task_id": str(task_id),
        "agent_id": str(agent_id),
        "attempt": str(attempt),
        "payload": json.dumps(payload, ensure_ascii=False),
    }
    return _sync_redis().xadd(STREAM_KEY, fields, maxlen=MAX_STREAM_LEN, approximate=True)


def publish_dispatch_event(task_id: int, agent_id: int, payload: dict[str, Any], attempt: int = 0) -> str:
    return _publish_event("dispatch", task_id=task_id, agent_id=agent_id, payload=payload, attempt=attempt)


def publish_cancel_event(task_id: int, agent_id: int, reason: str = "") -> str:
    payload = {
        "type": "task_cancel",
        "task_id": task_id,
        "reason": reason,
    }
    return _publish_event("cancel", task_id=task_id, agent_id=agent_id, payload=payload, attempt=0)
