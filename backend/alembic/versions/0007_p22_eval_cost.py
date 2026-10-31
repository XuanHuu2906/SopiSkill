"""P2.2 — LLM usage/cost accounting and job budget control

Revision ID: 0007_p22_eval_cost
Revises: 0006_p2sr_source_research
Create Date: 2026-10-31

Phạm vi (expand-only, không drop/không sửa dữ liệu cũ):
  - Bảng `llm_usage_events`: metadata từng lời gọi LLM (provider/model/kind/
    token/latency/cost estimate). KHÔNG chứa prompt hay nội dung sinh ra.
  - Cột tổng hợp trên `generation_jobs`: `llm_calls`, `prompt_tokens`,
    `completion_tokens`, `cost_estimate_usd` để API trả usage mà không phải
    aggregate bảng event mỗi request.
  - Index theo `job_id` và `created_at` cho truy vấn cost theo thời gian.

`cost_estimate_usd` để NULL khi chưa cấu hình giá model — NULL nghĩa là "chưa
biết", không phải miễn phí. Rows cũ có tổng token NULL và llm_calls = 0.

Downgrade: drop index + cột mới + bảng mới. Mất lịch sử usage/chi phí (không thể
khôi phục từ schema); dữ liệu course/lesson/job không bị đụng tới.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_p22_eval_cost"
down_revision: Union[str, None] = "0006_p2sr_source_research"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JOB_COLUMNS = [
    (
        "llm_calls",
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
    ),
    ("prompt_tokens", sa.Column("prompt_tokens", sa.Integer(), nullable=True)),
    ("completion_tokens", sa.Column("completion_tokens", sa.Integer(), nullable=True)),
    ("cost_estimate_usd", sa.Column("cost_estimate_usd", sa.Float(), nullable=True)),
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


def _table_names(conn) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()

    existing = _columns(conn, "generation_jobs")
    for name, column in _JOB_COLUMNS:
        if name not in existing:
            op.add_column("generation_jobs", column)

    if "llm_usage_events" not in _table_names(conn):
        op.create_table(
            "llm_usage_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "job_id",
                sa.Uuid(),
                sa.ForeignKey("generation_jobs.id"),
                nullable=True,
            ),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("finish_reason", sa.Text(), nullable=True),
            sa.Column("cost_estimate_usd", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    indexes = _index_names(conn, "llm_usage_events")
    if "ix_llm_usage_events_job_id" not in indexes:
        op.create_index("ix_llm_usage_events_job_id", "llm_usage_events", ["job_id"])
    if "ix_llm_usage_events_created_at" not in indexes:
        op.create_index(
            "ix_llm_usage_events_created_at", "llm_usage_events", ["created_at"]
        )


def downgrade() -> None:
    conn = op.get_bind()

    indexes = _index_names(conn, "llm_usage_events")
    if "ix_llm_usage_events_created_at" in indexes:
        op.drop_index("ix_llm_usage_events_created_at", table_name="llm_usage_events")
    if "ix_llm_usage_events_job_id" in indexes:
        op.drop_index("ix_llm_usage_events_job_id", table_name="llm_usage_events")

    if "llm_usage_events" in _table_names(conn):
        op.drop_table("llm_usage_events")

    existing = _columns(conn, "generation_jobs")
    for name, _column in reversed(_JOB_COLUMNS):
        if name in existing:
            op.drop_column("generation_jobs", name)
