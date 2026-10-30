"""P1.2 — reliable generation jobs: atomic claim, lease/heartbeat, dispatch outbox

Revision ID: 0004_p12_job_reliability
Revises: 0003_p11_quiz_integrity
Create Date: 2026-10-30

Expand-only (không drop/xóa dữ liệu, job cũ giữ nguyên):
  - proposal_version   : pin version proposal được duyệt cho job (snapshot).
  - dispatched_at      : outbox marker — NULL = committed nhưng chưa gửi broker.
  - dispatch_attempts  : số lần thử gửi broker (observability, không phải claim).
  - lease_expires_at   : lease của worker đang chạy job (chống chạy song song).
  - heartbeat_at       : worker cập nhật theo từng lesson.
  - max_attempts       : giới hạn retry bounded cho một job.
  - last_error_code    : mã lỗi ngắn (không chứa prompt/nội dung người dùng).
  - index (status, created_at) cho reconciler sweep.

Downgrade: drop index + các cột vừa thêm. Không khuyến nghị chạy trên DB thật;
dùng restore từ backup nếu cần quay lui (job đang chạy sẽ mất lease info).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_p12_job_reliability"
down_revision: Union[str, None] = "0003_p11_quiz_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ("proposal_version", sa.Column("proposal_version", sa.Integer(), nullable=True)),
    ("dispatched_at", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True)),
    (
        "dispatch_attempts",
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
    ),
    ("lease_expires_at", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)),
    ("heartbeat_at", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)),
    (
        "max_attempts",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    ),
    ("last_error_code", sa.Column("last_error_code", sa.Text(), nullable=True)),
]


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def _index_names(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    conn = op.get_bind()
    existing = _columns(conn, "generation_jobs")
    for name, column in _COLUMNS:
        if name not in existing:
            op.add_column("generation_jobs", column)

    if "ix_generation_jobs_status_created" not in _index_names(conn, "generation_jobs"):
        op.create_index(
            "ix_generation_jobs_status_created",
            "generation_jobs",
            ["status", "created_at"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if "ix_generation_jobs_status_created" in _index_names(conn, "generation_jobs"):
        op.drop_index("ix_generation_jobs_status_created", table_name="generation_jobs")

    existing = _columns(conn, "generation_jobs")
    for name, _column in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("generation_jobs", name)
