"""Object storage reader & writer for `ai-engine` (memory backend for tests, MinIO/S3 for runtime)."""

from __future__ import annotations

import asyncio
import io
from urllib.parse import urlsplit

from minio import Minio

from app.core.config import Settings, get_settings


class SourceStorageError(RuntimeError):
    """Raised when a source object cannot be read or written in storage."""


class MemorySourceStorage:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._content_types: dict[str, str] = {}

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._objects[key] = data
        self._content_types[key] = content_type

    async def put_bytes_async(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.put_bytes(key, data, content_type=content_type)

    async def get_bytes(self, key: str) -> bytes:
        if key not in self._objects:
            raise SourceStorageError(f"Object not found in memory storage: {key}")
        return self._objects[key]

    async def delete_prefix(self, prefix: str) -> int:
        if not prefix.startswith("reels-audio/"):
            raise SourceStorageError(f"Refusing to delete non-reel prefix: {prefix}")
        matching = [k for k in list(self._objects.keys()) if k.startswith(prefix)]
        for k in matching:
            self._objects.pop(k, None)
            self._content_types.pop(k, None)
        return len(matching)


class MinioSourceStorage:
    def __init__(self, settings: Settings) -> None:
        parsed = urlsplit(settings.s3_endpoint)
        endpoint = parsed.netloc or parsed.path
        secure = settings.s3_secure or parsed.scheme == "https"
        self._bucket = settings.s3_bucket
        self._bucket_ready = False
        self._client = Minio(
            endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=secure,
        )

    def _ensure_bucket_sync(self) -> None:
        if self._bucket_ready:
            return
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
        self._bucket_ready = True

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket_sync()
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def _read_sync(self, key: str) -> bytes:
        resp = self._client.get_object(self._bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        try:
            self._put_sync(key, data, content_type)
        except Exception as exc:
            raise SourceStorageError(f"Failed to upload object to S3 ({type(exc).__name__}).") from exc

    async def put_bytes_async(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        try:
            await asyncio.to_thread(self._put_sync, key, data, content_type)
        except Exception as exc:
            raise SourceStorageError(f"Failed to upload object to S3 ({type(exc).__name__}).") from exc

    async def get_bytes(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._read_sync, key)
        except Exception as exc:
            raise SourceStorageError(f"Failed to download object from S3 ({type(exc).__name__}).") from exc

    def _delete_prefix_sync(self, prefix: str) -> int:
        if not self._client.bucket_exists(self._bucket):
            return 0
        deleted = 0
        for obj in self._client.list_objects(self._bucket, prefix=prefix, recursive=True):
            if obj.object_name:
                self._client.remove_object(self._bucket, obj.object_name)
                deleted += 1
        return deleted

    async def delete_prefix(self, prefix: str) -> int:
        if not prefix.startswith("reels-audio/"):
            raise SourceStorageError(f"Refusing to delete non-reel prefix: {prefix}")
        try:
            return await asyncio.to_thread(self._delete_prefix_sync, prefix)
        except Exception as exc:
            raise SourceStorageError(f"Failed to delete S3 prefix ({type(exc).__name__}).") from exc


_memory_singleton = MemorySourceStorage()


def get_source_storage(settings: Settings | None = None) -> MemorySourceStorage | MinioSourceStorage:
    cfg = settings or get_settings()
    if (cfg.source_storage_backend or "memory").strip().lower() == "s3":
        return MinioSourceStorage(cfg)
    return _memory_singleton
