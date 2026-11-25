"""Object storage reader for `ai-worker-ingest` (memory backend for tests, MinIO/S3 for runtime)."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from minio import Minio

from app.core.config import Settings, get_settings


class SourceStorageError(RuntimeError):
    """Raised when a source object cannot be read from storage."""


class MemorySourceStorage:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put_bytes(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    async def get_bytes(self, key: str) -> bytes:
        if key not in self._objects:
            raise SourceStorageError(f"Object not found in memory storage: {key}")
        return self._objects[key]


class MinioSourceStorage:
    def __init__(self, settings: Settings) -> None:
        parsed = urlsplit(settings.s3_endpoint)
        endpoint = parsed.netloc or parsed.path
        secure = settings.s3_secure or parsed.scheme == "https"
        self._bucket = settings.s3_bucket
        self._client = Minio(
            endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=secure,
        )

    def _read_sync(self, key: str) -> bytes:
        resp = self._client.get_object(self._bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    async def get_bytes(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._read_sync, key)
        except Exception as exc:
            raise SourceStorageError(f"Failed to download object from S3 ({type(exc).__name__}).") from exc


_memory_singleton = MemorySourceStorage()


def get_source_storage(settings: Settings | None = None) -> MemorySourceStorage | MinioSourceStorage:
    cfg = settings or get_settings()
    if (cfg.source_storage_backend or "memory").strip().lower() == "s3":
        return MinioSourceStorage(cfg)
    return _memory_singleton
