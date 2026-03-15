import json
from functools import lru_cache

import redis

from client_agents.dispatch_stream import _resolve_redis_url


ACTIVE_LINE_KEY_PREFIX = "agent_task_active_line:"


def _active_line_key(task_id: int | str) -> str:
    return f"{ACTIVE_LINE_KEY_PREFIX}{task_id}"


@lru_cache(maxsize=1)
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(_resolve_redis_url(), decode_responses=True)


def get_active_line(task_id: int | str) -> dict | None:
    raw = _redis_client().get(_active_line_key(task_id))
    if not raw:
        return None

    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None

    return data if isinstance(data, dict) else None


def set_active_line(task_id: int | str, payload: dict) -> None:
    _redis_client().set(
        _active_line_key(task_id),
        json.dumps(payload, ensure_ascii=False),
    )


def clear_active_line(task_id: int | str) -> None:
    _redis_client().delete(_active_line_key(task_id))
