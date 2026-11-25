"""Reusable Redis Streams consumer engine (`XREADGROUP`, `XAUTOCLAIM`, heartbeat, retry, DLQ).

Compatible with KEDA `redis-streams` ScaledObject (`queue:ai:llm`, `queue:ai:ingest`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


def default_consumer_name(prefix: str) -> str:
    return f"{prefix}-{socket.gethostname()}-{os.getpid()}"


class RedisStreamWorker:
    """Reliable at-least-once consumer group worker over Redis 7 Streams."""

    def __init__(
        self,
        *,
        redis: Redis,
        stream_key: str,
        group_name: str,
        dlq_key: str,
        consumer_name: str,
        handler: JobHandler,
        claim_idle_ms: int = 300_000,
        max_retries: int = 3,
        block_ms: int = 2_000,
    ) -> None:
        self.redis = redis
        self.stream_key = stream_key
        self.group_name = group_name
        self.dlq_key = dlq_key
        self.consumer_name = consumer_name
        self.handler = handler
        self.claim_idle_ms = claim_idle_ms
        self.max_retries = max(1, max_retries)
        self.block_ms = block_ms
        self._running = False

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                name=self.stream_key,
                groupname=self.group_name,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def write_heartbeat(self) -> None:
        key = f"worker:heartbeat:{self.group_name}:{self.consumer_name}"
        await self.redis.set(key, "alive", ex=60)

    def _decode_message(self, fields: dict[Any, Any]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for k, v in fields.items():
            ks = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            vs = v.decode("utf-8") if isinstance(v, bytes) else str(v)
            decoded[ks] = vs
        if "data" in decoded:
            return json.loads(decoded["data"])
        return decoded

    async def process_entry(self, entry_id: str | bytes, fields: dict[Any, Any]) -> bool:
        entry_id_str = entry_id.decode("utf-8") if isinstance(entry_id, bytes) else str(entry_id)
        try:
            message = self._decode_message(fields)
        except Exception as exc:  # noqa: BLE001 — poison payload goes straight to DLQ
            logger.error("stream_poison_payload stream=%s id=%s err=%s", self.stream_key, entry_id_str, type(exc).__name__)
            await self.redis.xadd(
                self.dlq_key,
                {"originalId": entry_id_str, "error": f"INVALID_JSON:{type(exc).__name__}"},
            )
            await self.redis.xack(self.stream_key, self.group_name, entry_id_str)
            return False

        attempt = int(message.get("attempt", 1))
        try:
            await self.handler(message)
            await self.redis.xack(self.stream_key, self.group_name, entry_id_str)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "stream_job_failed stream=%s id=%s attempt=%d/%d err=%s",
                self.stream_key,
                entry_id_str,
                attempt,
                self.max_retries,
                type(exc).__name__,
            )
            if attempt < self.max_retries:
                next_msg = dict(message)
                next_msg["attempt"] = attempt + 1
                await self.redis.xadd(
                    self.stream_key,
                    {"data": json.dumps(next_msg, ensure_ascii=False, separators=(",", ":"))},
                )
            else:
                await self.redis.xadd(
                    self.dlq_key,
                    {
                        "originalId": entry_id_str,
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                        "data": json.dumps(message, ensure_ascii=False, separators=(",", ":")),
                    },
                )
            await self.redis.xack(self.stream_key, self.group_name, entry_id_str)
            return False

    async def reclaim_stale(self, *, count: int = 10) -> int:
        """Reclaim abandoned pending messages from crashed consumers via XAUTOCLAIM."""
        result = await self.redis.xautoclaim(
            name=self.stream_key,
            groupname=self.group_name,
            consumername=self.consumer_name,
            min_idle_time=self.claim_idle_ms,
            start_id="0-0",
            count=count,
        )
        # redis-py returns (next_start_id, [(entry_id, fields), ...], deleted_ids)
        entries = result[1] if len(result) > 1 else []
        processed = 0
        for entry_id, fields in entries:
            await self.process_entry(entry_id, fields)
            processed += 1
        return processed

    async def poll_once(self, *, count: int = 10) -> int:
        """Read and process one batch from the consumer group (`>`)."""
        response = await self.redis.xreadgroup(
            groupname=self.group_name,
            consumername=self.consumer_name,
            streams={self.stream_key: ">"},
            count=count,
            block=self.block_ms,
        )
        processed = 0
        for _stream, entries in response or []:
            for entry_id, fields in entries:
                await self.process_entry(entry_id, fields)
                processed += 1
        return processed

    async def run_forever(self) -> None:
        await self.ensure_group()
        self._running = True
        tick = 0
        logger.info("stream_worker_started stream=%s group=%s consumer=%s", self.stream_key, self.group_name, self.consumer_name)
        while self._running:
            await self.write_heartbeat()
            if tick % 5 == 0:
                await self.reclaim_stale()
            await self.poll_once()
            tick += 1

    def stop(self) -> None:
        self._running = False


async def enqueue_stream_job(redis: Redis, stream_key: str, message: dict[str, Any]) -> str:
    """Helper used by tests/tools to enqueue a JSON job envelope onto a Redis Stream."""
    entry_id = await redis.xadd(
        stream_key,
        {"data": json.dumps(message, ensure_ascii=False, separators=(",", ":"))},
    )
    return entry_id.decode("utf-8") if isinstance(entry_id, bytes) else str(entry_id)
