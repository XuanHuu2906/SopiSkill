"""Idempotency helpers chống tạo trùng course/attempt do retry."""

import hashlib


def client_id_hash(client_id: str) -> str:
    """Hash client id để tránh lưu raw id quá dài; vẫn unique theo nội dung."""
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:40]
