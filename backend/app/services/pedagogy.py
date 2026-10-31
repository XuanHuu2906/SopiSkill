"""Pedagogy layer (P2.1): learner profile + curriculum knowledge graph.

Hai trách nhiệm tách biệt, **không** phải "AI tự do":

1. `extract_learner_profile` — rule-based, deterministic, đọc chính câu trả lời
   phỏng vấn của người học. Không suy diễn thuộc tính nhạy cảm (tuổi, giới,
   sức khỏe, quốc tịch…); chỉ chuẩn hoá những gì người học tự nêu.
2. `normalize_curriculum` / `validate_curriculum` — chuẩn hoá lộ trình thành
   DAG prerequisite (topological sort) trên các skill gắn với từng bài học.

Dữ liệu curriculum nằm trong `ProposalPayload` (JSON), không cần bảng mới.
"""

import logging
import re

from app.providers.base import SchemaInvalidError
from app.schemas.schemas import CurriculumSkill, LearnerProfile, ProposalPayload

logger = logging.getLogger(__name__)

MAX_SKILLS = 48
MAX_EDGES = 96

_LEVEL_BEGINNER = (
    "chưa biết",
    "chưa từng",
    "chưa tiếp xúc",
    "mới bắt đầu",
    "mới học",
    "người mới",
    "cơ bản",
    "beginner",
    "from scratch",
    "chưa có kinh nghiệm",
    "zero",
)
_LEVEL_INTERMEDIATE = (
    "đã biết",
    "đã học qua",
    "đã từng",
    "trung bình",
    "intermediate",
    "có chút kinh nghiệm",
    "biết sơ",
)
_LEVEL_ADVANCED = (
    "nâng cao",
    "chuyên sâu",
    "thành thạo",
    "advanced",
    "expert",
    "đã có kinh nghiệm",
    "nhiều năm",
    "senior",
)

_STYLE_HANDS_ON = ("thực hành", "làm ví dụ", "hands-on", "coding", "thực chiến", "bài tập")
_STYLE_THEORY = ("lý thuyết", "đọc hiểu", "theory", "giải thích")
_STYLE_PROJECT = ("dự án", "project", "sản phẩm", "ứng dụng thật")
_STYLE_VISUAL = ("video", "hình ảnh", "sơ đồ", "trực quan")

_DEPTH_BROAD = ("phủ rộng", "tổng quan", "bao quát", "rộng", "overview", "broad")
_DEPTH_DEEP = ("đi sâu", "chuyên sâu", "chi tiết", "deep", "in-depth", "nâng cao")

_TIME_UNIT_MINUTES = {"phút": 1, "giờ": 60, "tiếng": 60, "h": 60, "hour": 60, "min": 1}

_BLOOM_LEVELS = ("remember", "understand", "apply", "analyze", "evaluate", "create")
_BLOOM_ORDER = {level: index for index, level in enumerate(_BLOOM_LEVELS)}


def _norm(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


# ---------- learner profile ----------


def _parse_weekly_minutes(text: str) -> int | None:
    """Đọc '3 giờ/tuần', '90 phút', '5-6h mỗi tuần' → phút/tuần (ước lượng thấp).

    Trả None nếu không có tín hiệu số + đơn vị thời gian.
    """
    pattern = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(?:-|–|đến|to)?\s*(\d+(?:[.,]\d+)?)?\s*"
        r"(phút|giờ|tiếng|tiếng/|h\b|hour|hours|min|mins|phut|gio)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    first = float(match.group(1).replace(",", "."))
    amount = first  # lấy cận dưới của khoảng để không thổi phồng thời gian
    unit = _norm(match.group(3)).rstrip("/")
    factor = 1
    for name, value in _TIME_UNIT_MINUTES.items():
        if unit.startswith(name):
            factor = value
            break
    minutes = int(round(amount * factor))
    if minutes <= 0 or minutes > 10_080:
        return None
    return minutes


def _detect_level(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    advanced = _contains_any(text, _LEVEL_ADVANCED)
    beginner = _contains_any(text, _LEVEL_BEGINNER)
    intermediate = _contains_any(text, _LEVEL_INTERMEDIATE)

    if advanced and beginner:
        warnings.append("Câu trả lời vừa nói 'mới bắt đầu' vừa nói 'nâng cao'; tạm xếp trung bình.")
        return "intermediate", warnings
    if advanced:
        return "advanced", warnings
    if intermediate:
        return "intermediate", warnings
    if beginner:
        return "beginner", warnings
    return "beginner", warnings


def _detect_styles(text: str) -> list[str]:
    styles: list[str] = []
    if _contains_any(text, _STYLE_HANDS_ON):
        styles.append("hands_on")
    if _contains_any(text, _STYLE_PROJECT):
        styles.append("project")
    if _contains_any(text, _STYLE_THEORY):
        styles.append("theory")
    if _contains_any(text, _STYLE_VISUAL):
        styles.append("visual")
    return styles[:6]


def _detect_depth(text: str) -> str:
    deep = _contains_any(text, _DEPTH_DEEP)
    broad = _contains_any(text, _DEPTH_BROAD)
    if deep and not broad:
        return "deep"
    if broad and not deep:
        return "broad"
    return "balanced"


def _detect_goal(answers: list[str]) -> str:
    """Goal = câu trả lời dài nhất có ý nghĩa (người học thường giải thích mục tiêu).

    Không dùng index cố định vì câu hỏi có thể do LLM sinh khác thứ tự.
    """
    candidates = [a.strip() for a in answers if a and len(a.strip()) >= 8]
    if not candidates:
        return ""
    return max(candidates, key=len)[:400]


def extract_learner_profile(
    questions: list[str], answers: list[str]
) -> LearnerProfile:
    """Suy hồ sơ từ chính câu trả lời (deterministic, không gọi LLM)."""
    joined = _norm(" \n ".join(a for a in answers if a))
    level, warnings = _detect_level(joined)
    weekly = _parse_weekly_minutes(joined)
    depth = _detect_depth(joined)

    if weekly is not None and depth == "deep" and weekly < 60:
        warnings.append("Thời gian mỗi tuần rất ít so với mong muốn đi sâu; lộ trình sẽ được rút gọn.")

    return LearnerProfile(
        goal=_detect_goal(answers),
        currentLevel=level,
        weeklyMinutes=weekly,
        preferredStyles=_detect_styles(joined),
        depth=depth,
        warnings=warnings,
    )


# ---------- curriculum graph ----------


def lesson_order(payload: ProposalPayload) -> list[str]:
    """Thứ tự bài học theo unit → lesson (giữ nguyên thứ tự proposal)."""
    return [title for unit in payload.units for title in unit.lessonTitles]


def _slug(text: str) -> str:
    ascii_text = re.sub(r"[^a-z0-9]+", "-", _norm(text)).strip("-")
    return ascii_text[:24] or "skill"


def fill_skills(payload: ProposalPayload) -> ProposalPayload:
    """Đảm bảo mỗi bài có đúng 1 skill; skill thiếu được sinh deterministic.

    LLM có thể trả skills rỗng/thiếu bài ⇒ server lấp phần thiếu để UI và DAG
    không bị "lỗ hổng" mà không cần đốt thêm request.
    """
    titles = lesson_order(payload)
    existing: dict[str, CurriculumSkill] = {}
    for skill in payload.skills:
        if skill.lesson not in existing:
            existing[skill.lesson] = skill

    filled: list[CurriculumSkill] = []
    for title in titles:
        skill = existing.get(title)
        if skill is None:
            skill = CurriculumSkill(
                id=_slug(title),
                title=title,
                lesson=title,
                bloomLevel="understand",
                outcome=f"Hiểu và áp dụng được nội dung '{title}'.",
            )
        filled.append(skill)

    payload.skills = filled[:MAX_SKILLS]
    return payload


def _topological_order(ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Kahn's algorithm; raise SchemaInvalidError khi có chu trình."""
    indegree = {node: 0 for node in ids}
    children: dict[str, list[str]] = {node: [] for node in ids}
    for parent, child in edges:
        children[parent].append(child)
        indegree[child] += 1

    ready = [node for node in ids if indegree[node] == 0]
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(ordered) != len(ids):
        remaining = [node for node in ids if node not in set(ordered)]
        raise SchemaInvalidError(
            "Lộ trình có chu trình prerequisite (DAG không hợp lệ): " + ", ".join(remaining[:8])
        )
    return ordered


def normalize_curriculum(payload: ProposalPayload) -> ProposalPayload:
    """Chuẩn hoá: bỏ cạnh trùng, bỏ self-loop, bỏ cạnh đi ngược thứ tự bài học.

    Chu trình thật (a→b→c→a) bị **từ chối** thay vì lặng lẽ sửa, vì đó là lỗi lộ
    trình chứ không phải lỗi thứ tự đơn lẻ.
    """
    payload = fill_skills(payload)
    position = {title: index for index, title in enumerate(lesson_order(payload))}
    skill_lesson = {skill.id: skill.lesson for skill in payload.skills}

    cleaned: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for parent, child in payload.prerequisites:
        edge = (str(parent).strip(), str(child).strip())
        if not edge[0] or not edge[1] or edge[0] == edge[1]:
            continue
        if edge in seen:
            continue
        seen.add(edge)
        cleaned.append(edge)

    # Bước 1: chu trình thật (a→b→c→a) là lỗi lộ trình ⇒ từ chối ngay, không tự sửa.
    known_ids = [skill.id for skill in payload.skills]
    known = set(known_ids)
    known_edges = [(p, c) for p, c in cleaned if p in known and c in known]
    _topological_order(known_ids, known_edges)

    # Bước 2: cạnh đơn lẻ đi ngược thứ tự bài (chưa tạo chu trình) bị loại kèm log,
    # vì thứ tự học đã do proposal quyết định.
    kept: list[tuple[str, str]] = []
    for parent, child in cleaned:
        parent_pos = position.get(skill_lesson.get(parent, ""), None)
        child_pos = position.get(skill_lesson.get(child, ""), None)
        if parent_pos is None or child_pos is None:
            kept.append((parent, child))  # để validate báo lỗi tham chiếu rõ ràng
            continue
        if parent_pos > child_pos:
            logger.warning(
                "curriculum edge pruned (prerequisite dạy sau kỹ năng phụ thuộc) parent=%s child=%s",
                parent,
                child,
            )
            continue
        kept.append((parent, child))

    payload.prerequisites = kept[:MAX_EDGES]
    return payload


def validate_curriculum(payload: ProposalPayload) -> ProposalPayload:
    """Kiểm tra DAG + phủ bài học. Raise SchemaInvalidError khi không hợp lệ."""
    titles = lesson_order(payload)
    if not titles:
        raise SchemaInvalidError("Lộ trình không có bài học nào.")

    seen_ids: set[str] = set()
    for skill in payload.skills:
        if skill.id in seen_ids:
            raise SchemaInvalidError(f"Skill id bị trùng: '{skill.id}'.")
        seen_ids.add(skill.id)

    covered = [skill.lesson for skill in payload.skills]
    if sorted(covered) != sorted(titles):
        missing = sorted(set(titles) - set(covered))
        extra = sorted(set(covered) - set(titles))
        raise SchemaInvalidError(
            "Curriculum không khớp bài học (thiếu: "
            + (", ".join(missing[:3]) or "không")
            + "; thừa: "
            + (", ".join(extra[:3]) or "không")
            + ")."
        )

    for parent, child in payload.prerequisites:
        if parent not in seen_ids or child not in seen_ids:
            raise SchemaInvalidError(f"Prerequisite tham chiếu skill không tồn tại: {parent} → {child}.")

    ids = [skill.id for skill in payload.skills]
    _topological_order(ids, list(payload.prerequisites))
    return payload


def curriculum_summary(payload: ProposalPayload) -> dict:
    """Tóm tắt cho UI/test: thứ tự học, số skill, độ sâu Bloom cao nhất."""
    ids = [skill.id for skill in payload.skills]
    try:
        ordered = _topological_order(ids, list(payload.prerequisites))
    except SchemaInvalidError:
        ordered = ids
    by_id = {skill.id: skill for skill in payload.skills}
    highest = max(
        (_BLOOM_ORDER.get(skill.bloomLevel, 0) for skill in payload.skills), default=0
    )
    return {
        "skillCount": len(payload.skills),
        "edgeCount": len(payload.prerequisites),
        "topologicalOrder": ordered,
        "highestBloomLevel": _BLOOM_LEVELS[highest],
        "orderedSkills": [
            {
                "id": by_id[skill_id].id,
                "title": by_id[skill_id].title,
                "lesson": by_id[skill_id].lesson,
                "bloomLevel": by_id[skill_id].bloomLevel,
            }
            for skill_id in ordered
            if skill_id in by_id
        ],
    }
