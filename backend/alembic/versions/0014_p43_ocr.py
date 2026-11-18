"""P4.3 — OCR provenance cho PDF scan

Revision ID: 0014_p43_ocr
Revises: 0013_p42_web_ingest
Create Date: 2026-11-01

Phạm vi (EXPAND-ONLY, không xóa/không sửa dữ liệu đã có):
  - `source_documents.text_source` (nullable Text) — `native` | `ocr` | `mixed`;
    NULL cho document P4.0/P4.2 cũ (KHÔNG backfill suy đoán).
  - `source_documents.ocr_pages` (Integer, NOT NULL, server_default '0').
  - `source_documents.ocr_engine` / `ocr_version` (nullable Text) — truy vết
    engine pretrained nào đã đọc tài liệu.
  - `source_chunks.text_source` (nullable Text) — provenance từng chunk.
  - `source_chunks.ocr_confidence` (Float, nullable) — confidence engine trả về,
    KHÔNG phải xác suất đúng đã hiệu chuẩn.
  - `source_chunks.ocr_bbox` (JSONB/JSON, nullable) — `[x0,y0,x1,y1]` chuẩn hoá
    theo trang trong [0,1].

Không đổi kiểu/không drop cột cũ ⇒ document cũ và citation cũ vẫn đọc được
(`text_source` NULL được tầng đọc coi là `native`).

Rollback (downgrade): drop 6 cột. KHÔNG xóa document/chunk. Nội dung đã OCR mất
nhãn provenance ⇒ mất khả năng phân biệt text máy đọc với text gốc; backup trước
trên DB thật.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_p43_ocr"
down_revision: Union[str, None] = "0013_p42_web_ingest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

DOCUMENT_COLUMNS = ("text_source", "ocr_pages", "ocr_engine", "ocr_version")
CHUNK_COLUMNS = ("text_source", "ocr_confidence", "ocr_bbox")


def _inspector():
    from sqlalchemy import inspect

    return inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _column_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {col["name"] for col in _inspector().get_columns(table)}


def upgrade() -> None:
    if not _has_table("source_documents") or not _has_table("source_chunks"):
        raise RuntimeError(
            "source_documents/source_chunks chưa tồn tại — cần chạy 0011_p40_source_ingest trước."
        )

    document_columns = _column_names("source_documents")
    if "text_source" not in document_columns:
        op.add_column("source_documents", sa.Column("text_source", sa.Text(), nullable=True))
    if "ocr_pages" not in document_columns:
        op.add_column(
            "source_documents",
            sa.Column("ocr_pages", sa.Integer(), nullable=False, server_default="0"),
        )
    if "ocr_engine" not in document_columns:
        op.add_column("source_documents", sa.Column("ocr_engine", sa.Text(), nullable=True))
    if "ocr_version" not in document_columns:
        op.add_column("source_documents", sa.Column("ocr_version", sa.Text(), nullable=True))

    chunk_columns = _column_names("source_chunks")
    if "text_source" not in chunk_columns:
        op.add_column("source_chunks", sa.Column("text_source", sa.Text(), nullable=True))
    if "ocr_confidence" not in chunk_columns:
        op.add_column("source_chunks", sa.Column("ocr_confidence", sa.Float(), nullable=True))
    if "ocr_bbox" not in chunk_columns:
        op.add_column("source_chunks", sa.Column("ocr_bbox", JSONVariant, nullable=True))


def downgrade() -> None:
    if not _has_table("source_documents") or not _has_table("source_chunks"):
        return

    chunk_columns = _column_names("source_chunks")
    for name in CHUNK_COLUMNS:
        if name in chunk_columns:
            op.drop_column("source_chunks", name)

    document_columns = _column_names("source_documents")
    for name in DOCUMENT_COLUMNS:
        if name in document_columns:
            op.drop_column("source_documents", name)
