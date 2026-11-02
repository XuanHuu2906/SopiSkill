"""P5.2b — Exposure logging (recommendation_events)

Revision ID: 0016_p52_exposure
Revises: 0015_p50_learner_profile
Create Date: 2026-11-02

Phạm vi (EXPAND-ONLY, không sửa/xoá bảng hay cột cũ):
  - `recommendation_events`: audit append-only của mỗi lần gợi ý đã hiển thị.
    Có `arm_kind`/`arm_id`/`reason_code`/`policy_version`/`propensity` và
    `lesson_content_version` (snapshot tại thời điểm gợi ý) để reward suy ra
    offline về sau mà không phải UPDATE bảng.

  UNIQUE(user_id, course_id, context_hash, arm_kind, arm_id) = idempotent cho
  "một exposure mỗi (context, arm)". KHÔNG phải đếm impression.

Rollback (downgrade): chỉ drop `recommendation_events`. KHÔNG đụng bảng cũ.
Mất exposure đã ghi (dữ liệu audit mới, không phải dữ liệu học) ⇒ backup trước
nếu đã bật P52_EXPOSURE_ENABLED trong thời gian dài.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_p52_exposure"
down_revision: Union[str, None] = "0015_p50_learner_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    from sqlalchemy import inspect

    return inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def upgrade() -> None:
    if not _has_table("users") or not _has_table("courses") or not _has_table("lessons"):
        raise RuntimeError(
            "users/courses/lessons chưa tồn tại — cần chạy các revision trước 0016."
        )

    if not _has_table("recommendation_events"):
        op.create_table(
            "recommendation_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "course_id",
                sa.Uuid(),
                sa.ForeignKey("courses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("context_hash", sa.Text(), nullable=False),
            sa.Column("policy_version", sa.Text(), nullable=False),
            sa.Column("arm_kind", sa.Text(), nullable=False),
            sa.Column(
                "arm_id",
                sa.Uuid(),
                sa.ForeignKey("lessons.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("lesson_content_version", sa.Integer(), nullable=False),
            sa.Column("propensity", sa.Float(), nullable=False),
            sa.Column("reason_code", sa.Text(), nullable=False),
            sa.Column("exposed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "user_id",
                "course_id",
                "context_hash",
                "arm_kind",
                "arm_id",
                name="uq_recommendation_event_context",
            ),
        )
        op.create_index(
            "ix_recommendation_events_course",
            "recommendation_events",
            ["course_id", "exposed_at"],
        )
        op.create_index(
            "ix_recommendation_events_user",
            "recommendation_events",
            ["user_id", "exposed_at"],
        )
        op.create_index(
            "ix_recommendation_events_user_id",
            "recommendation_events",
            ["user_id"],
        )


def downgrade() -> None:
    if _has_table("recommendation_events"):
        op.drop_table("recommendation_events")
