"""Storage adapter cho tài liệu nguồn (P4.0) — private object storage.

Nguyên tắc bảo mật:
  - Object key do SERVER sinh ngẫu nhiên (`sources/<source_id>/<uuid4>`), không
    bao giờ lấy path/tên file từ client. Không có API nào trả object key ra
    ngoài; người dùng chỉ thấy tên hiển thị đã làm sạch.
  - Bucket private: không bật policy public. Mọi lần đọc đều qua service sau khi
    đã xác thực ownership.
  - Không log bytes, text hay credential. Log chỉ `source_id`/`document_id` và
    kích thước.
  - Chưa cấu hình ⇒ `StorageNotConfigured` (API trả 503), KHÔNG ghi file vào thư
    mục tạm ngầm rồi coi như thành công.

Backend hiện tại: S3-compatible (MinIO). Interface giữ hẹp (`put`, `get`,
`delete`) để thêm backend khác mà không đổi ingest service.
"""

from __future__ import annotations

import io
import logging
import uuid

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_MAX_PREFIX_LEN = 64


class StorageError(Exception):
    """Lỗi kho lưu trữ — message an toàn, không chứa credential/nội dung."""

    code = "STORAGE_ERROR"


class StorageNotConfigured(StorageError):
    code = "STORAGE_NOT_CONFIGURED"


class StorageNotFound(StorageError):
    code = "SOURCE_DOCUMENT_NOT_FOUND"


def build_object_key(source_id: uuid.UUID) -> str:
    """Key ngẫu nhiên, không suy ra từ tên file người dùng."""
    return f"sources/{source_id}/{uuid.uuid4().hex}"


def sanitize_filename(name: str | None, *, default: str = "document.pdf") -> str:
    """Chỉ giữ basename ASCII-ish an toàn để hiển thị; không dùng làm path."""
    raw = (name or "").replace("\\", "/").split("/")[-1].strip()
    if not raw:
        return default
    allowed = [ch for ch in raw if ch.isprintable() and ch not in '"\'<>|:*?\x00']
    cleaned = "".join(allowed).strip(". ")
    if not cleaned:
        return default
    return cleaned[:120]


class Storage:
    """Interface tối thiểu; implement bằng S3-compatible client."""

    name = "base"

    def put(self, key: str, data: bytes, *, content_type: str = "application/pdf") -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str, *, limit: int = 200) -> None:
        raise NotImplementedError


class S3Storage(Storage):
    """MinIO/S3-compatible backend dùng `minio` SDK (server-side credentials)."""

    name = "s3"

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        region: str = "us-east-1",
        auto_create_bucket: bool = True,
    ) -> None:
        if not endpoint or not access_key or not secret_key or not bucket:
            raise StorageNotConfigured("Kho lưu trữ nguồn chưa được cấu hình.")
        self.bucket = bucket
        try:
            from minio import Minio
        except ImportError as exc:  # pragma: no cover — chỉ khi thiếu dependency
            raise StorageNotConfigured("Thiếu thư viện minio trên server.") from exc

        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )
        self._ensure_bucket() if auto_create_bucket else None

    def _ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
                logger.info("source storage bucket created bucket=%s", self.bucket)
        except Exception as exc:  # noqa: BLE001 — không lộ credential ra log
            raise StorageError(f"Không khởi tạo được bucket: {type(exc).__name__}") from exc

    def put(self, key: str, data: bytes, *, content_type: str = "application/pdf") -> None:
        try:
            self._client.put_object(
                self.bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Ghi tài liệu thất bại: {type(exc).__name__}") from exc

    def get(self, key: str) -> bytes:
        from minio.error import S3Error

        response = None
        try:
            response = self._client.get_object(self.bucket, key)
            return response.read()
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchBucket", "NoSuchObject"):
                raise StorageNotFound("Không tìm thấy tài liệu trong kho lưu trữ.") from exc
            raise StorageError(f"Đọc tài liệu thất bại: {exc.code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Đọc tài liệu thất bại: {type(exc).__name__}") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                    response.release_conn()
                except Exception:  # đóng kết nối best-effort; không che lỗi đọc ở trên
                    pass  # nosec B110

    def delete(self, key: str) -> None:
        try:
            self._client.remove_object(self.bucket, key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Xóa tài liệu thất bại: {type(exc).__name__}") from exc

    def delete_prefix(self, prefix: str, *, limit: int = 200) -> None:
        from minio.deleteobjects import DeleteObject

        if len(prefix) > _MAX_PREFIX_LEN:
            raise StorageError("Prefix không hợp lệ.")
        try:
            objects = self._client.list_objects(self.bucket, prefix=prefix, recursive=True)
            batch = []
            for obj in objects:
                batch.append(DeleteObject(obj.object_name))
                if len(batch) >= limit:
                    list(self._client.remove_objects(self.bucket, batch))
                    batch = []
            if batch:
                list(self._client.remove_objects(self.bucket, batch))
        except Exception as exc:  # noqa: BLE001
            # Xóa storage là best-effort sau khi DB đã xóa; không làm request sập.
            logger.warning("source storage prefix delete failed code=%s", type(exc).__name__)


class InMemoryStorage(Storage):
    """Chỉ dùng cho test/dev không có MinIO. Key vẫn do server sinh ngẫu nhiên."""

    name = "memory"

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str = "application/pdf") -> None:
        self._objects[key] = bytes(data)

    def get(self, key: str) -> bytes:
        if key not in self._objects:
            raise StorageNotFound("Không tìm thấy tài liệu trong kho lưu trữ.")
        return self._objects[key]

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def delete_prefix(self, prefix: str, *, limit: int = 200) -> None:
        for key in [k for k in self._objects if k.startswith(prefix)][:limit]:
            self._objects.pop(key, None)


_memory_singleton = InMemoryStorage()


def storage_configured() -> bool:
    return get_settings().source_storage_configured


def get_storage() -> Storage:
    """Trả storage đã cấu hình. Chưa cấu hình ⇒ `StorageNotConfigured`.

    Không có nhánh fallback ghi đĩa: ingestion phải chủ động bật bằng cấu hình.
    """
    settings = get_settings()
    if not settings.source_storage_configured:
        raise StorageNotConfigured("Kho lưu trữ nguồn chưa được cấu hình trên server.")
    if settings.source_storage_backend.strip().lower() == "memory":
        # Chỉ dùng cho test/dev: nội dung nằm trong RAM tiến trình.
        return _memory_singleton
    return S3Storage(
        endpoint=settings.source_storage_endpoint,
        access_key=settings.source_storage_access_key,
        secret_key=settings.source_storage_secret_key,
        bucket=settings.source_storage_bucket,
        secure=settings.source_storage_secure,
        region=settings.source_storage_region,
        auto_create_bucket=settings.source_storage_auto_create_bucket,
    )


def get_test_storage() -> InMemoryStorage:
    """Storage in-memory dùng cho pytest (không gọi network)."""
    return _memory_singleton
