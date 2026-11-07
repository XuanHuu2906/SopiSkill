"""P5.0 — Learner Profile, Mastery Baseline & FSRS

Revision ID: 0015_p50_learner_profile
Revises: 0014_p43_ocr
Create Date: 2026-11-02

Phạm vi (EXPAND-ONLY, không xóa/không sửa dữ liệu đã có):
  - `skills`: skill ổn định trong 1 course, backfill từ proposal payload.
  - `lesson_skills`: liên kết lesson ↔ skill (hiện 1:1 nhưng PK cho phép nhiều).
  - `skill_mastery`: snapshot mastery theo (user, skill) — heuristic, không phải
    xác suất đã hiệu chuẩn.
  - `review_cards`: snapshot FSRS hiện tại theo (user, lesson).
  - `review_events`: audit append-only của mỗi lần review.

Không đổi/drop bảng hay cột cũ ⇒ attempt, XP và progress của P1.1 giữ nguyên.

Rollback (downgrade): drop 5 bảng mới theo thứ tự ngược FK. KHÔNG đụng bảng cũ.
Mất lịch ôn tập và mastery đã tích luỹ ⇒ backup trước trên DB thật.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_p50_learner_profile"
down_revision: Union[str, None] = "0014_p43_ocr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    from sqlalchemy import inspect

    return inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def upgrade() -> None:
    if not _has_table("courses") or not _has_table("lessons") or not _has_table("users"):
        raise RuntimeError(
            "courses/lessons/users chưa tồn tại — cần chạy các revision trước 0015."
        )

    if not _has_table("skills"):
        op.create_table(
            "skills",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "course_id",
                sa.Uuid(),
                sa.ForeignKey("courses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("key", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("bloom_level", sa.Text(), nullable=False, server_default="understand"),
            sa.Column("outcome", sa.Text(), nullable=False, server_default=""),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("course_id", "key", name="uq_skill_course_key"),
        )
        op.create_index("ix_skills_course_id", "skills", ["course_id"])

    if not _has_table("lesson_skills"):
        op.create_table(
            "lesson_skills",
            sa.Column(
                "lesson_id",
                sa.Uuid(),
                sa.ForeignKey("lessons.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "skill_id",
                sa.Uuid(),
                sa.ForeignKey("skills.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_lesson_skills_skill", "lesson_skills", ["skill_id"])

    if not _has_table("skill_mastery"):
        op.create_table(
            "skill_mastery",
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "skill_id",
                sa.Uuid(),
                sa.ForeignKey("skills.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("correct", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mastery_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_skill_mastery_skill", "skill_mastery", ["skill_id"])

    if not _has_table("review_cards"):
        op.create_table(
            "review_cards",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "lesson_id",
                sa.Uuid(),
                sa.ForeignKey("lessons.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "skill_id",
                sa.Uuid(),
                sa.ForeignKey("skills.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("state", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("step", sa.Integer(), nullable=True),
            sa.Column("stability", sa.Float(), nullable=True),
            sa.Column("difficulty", sa.Float(), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scheduler_version", sa.Text(), nullable=False),
            sa.Column(
                "created_from_attempt_id",
                sa.Uuid(),
                sa.ForeignKey("lesson_attempts.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "lesson_id", name="uq_review_card_user_lesson"),
        )
        op.create_index("ix_review_cards_user_id", "review_cards", ["user_id"])
        op.create_index("ix_review_cards_user_due", "review_cards", ["user_id", "due_at"])

    if not _has_table("review_events"):
        op.create_table(
            "review_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "card_id",
                sa.Uuid(),
                sa.ForeignKey("review_cards.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("elapsed_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("scheduled_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_ms", sa.BigInteger(), nullable=True),
            sa.Column("state_before", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("state_after", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("scheduler_version", sa.Text(), nullable=False),
            sa.Column("client_review_id", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("card_id", "client_review_id", name="uq_review_event_client_id"),
        )
        op.create_index("ix_review_events_card_id", "review_events", ["card_id"])
        op.create_index(
            "ix_review_events_card_reviewed", "review_events", ["card_id", "reviewed_at"]
        )
        op.create_index(
            "ix_review_events_user_reviewed", "review_events", ["user_id", "reviewed_at"]
        )


def downgrade() -> None:
    for table in ("review_events", "review_cards", "skill_mastery", "lesson_skills", "skills"):
        if _has_table(table):
            op.drop_table(table)
