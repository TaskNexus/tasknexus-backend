import asyncio
import json
import os
import socket

import redis.asyncio as redis_async
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from redis.exceptions import ResponseError

from client_agents.dispatch_stream import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS,
    GROUP_NAME,
    MAX_RETRIES,
    MAX_STREAM_LEN,
    STREAM_KEY,
    _resolve_redis_url,
)


class Command(BaseCommand):
    help = "Run async dispatcher for agent task dispatch/cancel events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--consumer-name",
            type=str,
            default="",
            help="Optional consumer name. Default: hostname-pid",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=int(os.environ.get("AGENT_DISPATCH_READ_COUNT", "10")),
            help="Max message count per xreadgroup call.",
        )
        parser.add_argument(
            "--block-ms",
            type=int,
            default=int(os.environ.get("AGENT_DISPATCH_BLOCK_MS", "5000")),
            help="Block timeout (milliseconds) for xreadgroup.",
        )

    def handle(self, *args, **options):
        consumer_name = options["consumer_name"] or f"{socket.gethostname()}-{os.getpid()}"
        count = options["count"]
        block_ms = options["block_ms"]
        asyncio.run(self._run(consumer_name=consumer_name, count=count, block_ms=block_ms))

    async def _run(self, consumer_name: str, count: int, block_ms: int):
        redis_client = redis_async.Redis.from_url(_resolve_redis_url(), decode_responses=True)
        channel_layer = get_channel_layer()
        self.stdout.write(
            self.style.SUCCESS(
                f"[agent_dispatcher] started, stream={STREAM_KEY}, group={GROUP_NAME}, consumer={consumer_name}"
            )
        )

        await self._ensure_group(redis_client)

        while True:
            try:
                reclaimed = await self._drain_pending(
                    redis_client=redis_client,
                    channel_layer=channel_layer,
                    consumer_name=consumer_name,
                    count=count,
                )
                if reclaimed:
                    continue

                messages = await redis_client.xreadgroup(
                    groupname=GROUP_NAME,
                    consumername=consumer_name,
                    streams={STREAM_KEY: ">"},
                    count=count,
                    block=block_ms,
                )
                if not messages:
                    continue

                for _, entries in messages:
                    for message_id, fields in entries:
                        await self._handle_message(redis_client, channel_layer, message_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"[agent_dispatcher] loop error: {exc}"))
                await asyncio.sleep(1)

    async def _ensure_group(self, redis_client: redis_async.Redis):
        try:
            await redis_client.xgroup_create(name=STREAM_KEY, groupname=GROUP_NAME, id="0", mkstream=True)
            self.stdout.write(self.style.SUCCESS(f"[agent_dispatcher] created group: {GROUP_NAME}"))
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _drain_pending(self, redis_client, channel_layer, consumer_name: str, count: int) -> bool:
        reclaimed_any = False
        start_id = "0-0"
        while True:
            next_start_id, messages, _ = await redis_client.xautoclaim(
                name=STREAM_KEY,
                groupname=GROUP_NAME,
                consumername=consumer_name,
                min_idle_time=60_000,
                start_id=start_id,
                count=count,
            )
            if not messages:
                break

            reclaimed_any = True
            for message_id, fields in messages:
                await self._handle_message(redis_client, channel_layer, message_id, fields)

            start_id = next_start_id
            if next_start_id == "0-0":
                break

        return reclaimed_any

    async def _handle_message(self, redis_client, channel_layer, message_id: str, fields: dict):
        event_type = fields.get("event_type", "")
        task_id = self._to_int(fields.get("task_id"))
        agent_id = self._to_int(fields.get("agent_id"))
        attempt = max(0, self._to_int(fields.get("attempt"), default=0))
        payload = self._load_payload(fields.get("payload", "{}"))

        should_retry = False
        retry_attempt = attempt + 1
        retry_error = ""

        try:
            if not task_id or not agent_id:
                return

            if event_type == "dispatch":
                should_send = await self._task_is_pending(task_id)
                if not should_send:
                    return

                await channel_layer.group_send(f"agent_{agent_id}", payload)
                await self._mark_dispatched(task_id)
            elif event_type == "cancel":
                await channel_layer.group_send(f"agent_{agent_id}", payload)
                await self._mark_cancelled(task_id)
            else:
                self.stderr.write(self.style.WARNING(f"[agent_dispatcher] unknown event_type: {event_type}"))
        except Exception as exc:  # noqa: BLE001
            retry_error = str(exc)
            if event_type == "dispatch" and retry_attempt <= MAX_RETRIES:
                should_retry = True
            else:
                await self._mark_dispatch_failed(task_id, retry_error)
        finally:
            await redis_client.xack(STREAM_KEY, GROUP_NAME, message_id)

        if should_retry:
            delay = min(BACKOFF_BASE_SECONDS * (2**attempt), BACKOFF_MAX_SECONDS)
            await self._mark_dispatch_retry(task_id, retry_attempt, retry_error)
            await asyncio.sleep(delay)
            await redis_client.xadd(
                STREAM_KEY,
                {
                    "event_type": "dispatch",
                    "task_id": str(task_id),
                    "agent_id": str(agent_id),
                    "attempt": str(retry_attempt),
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
                maxlen=MAX_STREAM_LEN,
                approximate=True,
            )

    @staticmethod
    def _to_int(value, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _load_payload(raw: str) -> dict:
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @sync_to_async
    def _task_is_pending(self, task_id: int) -> bool:
        from client_agents.models import AgentTask

        return AgentTask.objects.filter(id=task_id, status="PENDING").exists()

    @sync_to_async
    def _mark_dispatched(self, task_id: int):
        from client_agents.models import AgentTask

        AgentTask.objects.filter(id=task_id, status="PENDING").update(
            status="DISPATCHED",
            dispatched_at=timezone.now(),
            error_message="",
        )

    @sync_to_async
    def _mark_cancelled(self, task_id: int):
        from client_agents.models import AgentTask

        AgentTask.objects.filter(id=task_id).filter(
            Q(status="PENDING") | Q(status="DISPATCHED") | Q(status="RUNNING")
        ).update(
            status="CANCELLED",
            finished_at=timezone.now(),
        )

    @sync_to_async
    def _mark_dispatch_retry(self, task_id: int, attempt: int, error: str):
        from client_agents.models import AgentTask

        AgentTask.objects.filter(id=task_id, status="PENDING").update(
            error_message=f"Dispatch retry {attempt}/{MAX_RETRIES}: {error}",
        )

    @sync_to_async
    def _mark_dispatch_failed(self, task_id: int, error: str):
        from client_agents.models import AgentTask

        AgentTask.objects.filter(id=task_id, status="PENDING").update(
            status="FAILED",
            error_message=f"Dispatch failed: {error}",
            finished_at=timezone.now(),
        )
