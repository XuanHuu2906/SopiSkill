"""P5.1 dataset extractor cho BKT — CHỈ ĐỌC, không tạo/ghi bảng.

Khác `rag_eval.py`: script này KHÔNG gọi `Base.metadata.create_all`, vì nó phải
chạy trên **database thật** (dev/prod có dữ liệu attempt). Nếu tạo bảng ở đây thì
bảng skill luôn tồn tại và schema cũ (`0012`) không bao giờ được phát hiện.

Đọc:
  - Chỉ attempt có `lesson_attempts.content_version == lessons.content_version`
    và `score_total > 0` (đồng bộ policy P1.1/P5.0).
  - `y = score_correct / score_total` (0..1, mục tiêu mềm).
  - Granularity:
      * `skill`  : JOIN `lesson_skills` → `skills`; attempt không gắn skill vẫn được
                   giữ với key `lesson:<id>` để không âm thầm mất dữ liệu.
      * `lesson` : key `lesson:<lesson_id>`.
    Nếu bảng `skills`/`lesson_skills` chưa tồn tại (schema `0012`), tự fallback
    về lesson và đặt `skill_granularity=false` — KHÔNG raise.

Không sửa dữ liệu, không commit, không in DSN kèm mật khẩu.
"""

from __future__ import annotations

import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

LENGTH_THRESHOLDS = (1, 2, 3, 5, 10, 20)
SKILL_TABLES = ("skills", "lesson_skills")


@dataclass
class Sequence:
    user_id: str
    key: str
    events: list[tuple[datetime, float]] = field(default_factory=list)


@dataclass
class DatasetReport:
    database: str
    skill_granularity: bool
    users: int
    sequences: int
    raw_attempts: int
    versioned_attempts: int
    length_histogram: dict[str, int]
    sequences_ge: dict[str, int]
    min_sequence: int = 5

    def as_dict(self) -> dict:
        return {
            "database": self.database,
            "skillGranularity": self.skill_granularity,
            "users": self.users,
            "sequences": self.sequences,
            "rawAttempts": self.raw_attempts,
            "versionedAttempts": self.versioned_attempts,
            "lengthHistogram": self.length_histogram,
            "sequencesGe": self.sequences_ge,
            "minSequence": self.min_sequence,
            "sequencesMeetingMin": self.sequences_ge.get(str(self.min_sequence), 0),
        }


def redact_dsn(dsn: str) -> str:
    """Ẩn mật khẩu trong DSN trước khi in/log."""
    try:
        parts = urllib.parse.urlsplit(dsn)
    except ValueError:
        return "<invalid dsn>"
    if parts.password is None:
        return dsn
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
    return urllib.parse.urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )


async def detect_tables(engine: AsyncEngine) -> set[str]:
    """`inspect(AsyncEngine)` không hợp lệ ⇒ phải đi qua `run_sync`."""
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))


def _as_utc(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    # SQLite lưu TEXT khi test dựng bảng tay.
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


async def load_sequences(
    engine: AsyncEngine,
    granularity: str = "skill",
    min_sequence: int = 5,
) -> tuple[list[Sequence], DatasetReport]:
    """Trả `(sequences, report)`. Chỉ SELECT; không ghi gì vào DB."""
    if granularity not in {"skill", "lesson"}:
        raise ValueError("granularity phải là 'skill' hoặc 'lesson'")

    tables = await detect_tables(engine)
    has_skill = all(name in tables for name in SKILL_TABLES)
    effective = granularity if (granularity == "skill" and has_skill) else "lesson"

    if "lesson_attempts" not in tables or "lessons" not in tables:
        # DB rỗng/chưa migrate: trả rỗng thay vì crash. Lỗi CỘT vẫn phải nổi lên.
        return [], DatasetReport(
            database="<masked>",
            skill_granularity=effective == "skill",
            users=0,
            sequences=0,
            raw_attempts=0,
            versioned_attempts=0,
            length_histogram={},
            sequences_ge={str(n): 0 for n in LENGTH_THRESHOLDS},
            min_sequence=int(min_sequence),
        )

    async with engine.connect() as conn:
        raw_attempts = int(
            (await conn.execute(text("SELECT COUNT(*) FROM lesson_attempts"))).scalar_one()
        )

        if effective == "skill":
            sql = """
                SELECT a.user_id, a.created_at, a.score_correct, a.score_total,
                       COALESCE(s.key, 'lesson:' || l.id) AS seq_key
                FROM lesson_attempts a
                JOIN lessons l ON l.id = a.lesson_id
                LEFT JOIN lesson_skills ls ON ls.lesson_id = l.id
                LEFT JOIN skills s ON s.id = ls.skill_id
                WHERE a.content_version = l.content_version AND a.score_total > 0
                ORDER BY a.created_at, a.id
            """
            prefix = "skill:"
        else:
            sql = """
                SELECT a.user_id, a.created_at, a.score_correct, a.score_total,
                       'lesson:' || l.id AS seq_key
                FROM lesson_attempts a
                JOIN lessons l ON l.id = a.lesson_id
                WHERE a.content_version = l.content_version AND a.score_total > 0
                ORDER BY a.created_at, a.id
            """
            prefix = ""

        rows = (await conn.execute(text(sql))).all()

    # Với granularity=skill nhưng skill fallback đã có sẵn prefix `lesson:`, không
    # thêm `skill:` lần nữa; khi có skill thật thì key cần prefix `skill:`.
    def _key(raw_key: str) -> str:
        if prefix and not raw_key.startswith("lesson:"):
            return f"{prefix}{raw_key}"
        return raw_key

    grouped: dict[tuple[str, str], Sequence] = {}
    for user_id, created_at, correct, total, raw_key in rows:
        key = _key(str(raw_key))
        bucket = grouped.get((str(user_id), key))
        if bucket is None:
            bucket = Sequence(user_id=str(user_id), key=key)
            grouped[(str(user_id), key)] = bucket
        y = _clamp01(float(correct) / float(total))
        bucket.events.append((_as_utc(created_at), y))

    sequences = sorted(
        grouped.values(), key=lambda seq: (seq.user_id, seq.key)
    )
    for seq in sequences:
        seq.events.sort(key=lambda item: item[0])

    lengths = Counter(len(seq.events) for seq in sequences)
    report = DatasetReport(
        database="<masked>",
        skill_granularity=effective == "skill",
        users=len({seq.user_id for seq in sequences}),
        sequences=len(sequences),
        raw_attempts=raw_attempts,
        versioned_attempts=len(rows),
        length_histogram={str(k): v for k, v in sorted(lengths.items())},
        sequences_ge={
            str(n): sum(1 for seq in sequences if len(seq.events) >= n)
            for n in LENGTH_THRESHOLDS
        },
        min_sequence=int(min_sequence),
    )
    return sequences, report


def summarize(report: DatasetReport, thresholds: dict) -> dict:
    """So report với ngưỡng; trả `enough` + lý do tiếng Việt cho từng ngưỡng thiếu."""
    min_sequences = int(thresholds.get("min_sequences", 30))
    min_events = int(thresholds.get("min_events", 300))

    # Gate dùng chuỗi ≥ `min_sequence` event (ngưỡng tối thiểu của BKT), không đếm user.
    qualifying = report.sequences_ge.get(str(report.min_sequence), 0)
    reasons: list[str] = []
    if qualifying < min_sequences:
        reasons.append(
            f"min_sequences={min_sequences}: chỉ có {qualifying} chuỗi "
            f"≥{report.min_sequence} event"
        )
    if report.versioned_attempts < min_events:
        reasons.append(
            f"min_events={min_events}: chỉ có {report.versioned_attempts} event đúng contentVersion"
        )
    return {
        "enough": not reasons,
        "reasons": reasons,
        "metrics": {
            "qualifyingSequences": qualifying,
            "versionedAttempts": report.versioned_attempts,
        },
    }
