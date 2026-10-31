"""P2.1 — learner profile, curriculum DAG, hierarchical generation (offline).

Chạy hoàn toàn offline với MockProvider: **không** phải bằng chứng AI thật, không
gọi mạng, không tốn phí. Phần real-provider E2E được ghi BLOCKED trong progress.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import CourseProposal
from app.providers import MockProvider, SchemaInvalidError
from app.providers.validation import validate_lesson, validate_proposal
from app.schemas.schemas import (
    CurriculumSkill,
    LessonContent,
    ProposalPayload,
    ProposalUnit,
    TeachBlock,
)
from app.services import pedagogy

PASSWORD = "Passw0rd!123"

EVAL_TOPICS = [
    "Python cho người mới",
    "Tâm lý học hành vi",
    "Kinh tế vĩ mô cơ bản",
    "React Server Components",
    "Machine learning nâng cao",
    "Viết luận tiếng Anh học thuật",
    "Quản trị dự án Agile",
    "Sinh thái học đại cương",
    "SQL tối ưu truy vấn",
    "Lịch sử nghệ thuật Phục hưng",
]


def csrf_headers(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


# ---------- learner profile ----------


def test_profile_extracts_level_time_and_style():
    profile = pedagogy.extract_learner_profile(
        [f"q{i}" for i in range(5)],
        [
            "Mình chưa từng học Python",
            "Mục tiêu là tự làm được một web app nhỏ để nộp đồ án",
            "Mỗi tuần mình dành 3 giờ",
            "Mình thích thực hành và làm dự án hơn đọc lý thuyết",
            "Mình muốn đi sâu vào backend",
        ],
    )
    assert profile.currentLevel == "beginner"
    assert profile.weeklyMinutes == 180
    assert profile.depth == "deep"
    assert "hands_on" in profile.preferredStyles
    assert "project" in profile.preferredStyles
    assert "web app" in profile.goal


def test_profile_advanced_and_ambiguous_level_warns():
    advanced = pedagogy.extract_learner_profile(
        [f"q{i}" for i in range(5)],
        ["Mình đã có nhiều năm kinh nghiệm", "mục tiêu chuyên sâu", "2 giờ", "thực hành", "nâng cao"],
    )
    assert advanced.currentLevel == "advanced"
    assert advanced.weeklyMinutes == 120

    ambiguous = pedagogy.extract_learner_profile(
        [f"q{i}" for i in range(5)],
        ["Mình mới bắt đầu nhưng cũng muốn học nâng cao", "mục tiêu", "1 giờ", "x", "y"],
    )
    assert ambiguous.currentLevel == "intermediate"
    assert any("trung bình" in w for w in ambiguous.warnings)


def test_profile_missing_time_is_none_not_guessed():
    profile = pedagogy.extract_learner_profile(
        [f"q{i}" for i in range(5)], ["a", "b", "c", "d", "e"]
    )
    assert profile.weeklyMinutes is None
    assert profile.currentLevel == "beginner"
    assert profile.depth == "balanced"


def test_profile_does_not_infer_sensitive_attributes():
    profile = pedagogy.extract_learner_profile(
        [f"q{i}" for i in range(5)],
        ["Mình 22 tuổi, nữ", "mục tiêu", "4h", "thực hành", "sâu"],
    )
    dumped = profile.model_dump()
    assert "age" not in dumped and "gender" not in dumped
    assert all("22" not in value for value in dumped["preferredStyles"])


# ---------- curriculum DAG ----------


def _payload(unlinked: bool = False) -> ProposalPayload:
    return ProposalPayload(
        name="Test",
        objective="obj",
        units=[
            ProposalUnit(title="U1", blurb="", lessonTitles=["A", "B"]),
            ProposalUnit(title="U2", blurb="", lessonTitles=["C"]),
        ],
        outcomes=["o1", "o2"],
        skills=[] if unlinked else [
            CurriculumSkill(id="a", title="A", lesson="A", bloomLevel="remember"),
            CurriculumSkill(id="b", title="B", lesson="B", bloomLevel="apply"),
            CurriculumSkill(id="c", title="C", lesson="C", bloomLevel="analyze"),
        ],
        prerequisites=[("a", "b"), ("b", "c")] if not unlinked else [],
    )


def test_curriculum_fills_missing_skills_deterministically():
    payload = validate_proposal(_payload(unlinked=True))
    assert [s.lesson for s in payload.skills] == ["A", "B", "C"]
    assert len({s.id for s in payload.skills}) == 3


def test_curriculum_cycle_is_rejected():
    payload = _payload()
    payload.prerequisites = [("a", "b"), ("b", "c"), ("c", "a")]
    with pytest.raises(SchemaInvalidError, match="chu trình"):
        pedagogy.validate_curriculum(pedagogy.normalize_curriculum(payload))


def test_curriculum_self_loop_and_backwards_edge_are_pruned():
    payload = _payload()
    payload.prerequisites = [("a", "a"), ("c", "a"), ("a", "b"), ("a", "b")]
    cleaned = pedagogy.normalize_curriculum(payload)
    assert ("a", "a") not in cleaned.prerequisites
    assert cleaned.prerequisites.count(("a", "b")) == 1
    assert ("c", "a") not in cleaned.prerequisites, "prerequisite dạy sau phải bị loại"
    assert cleaned.prerequisites == [("a", "b")]


def test_curriculum_mutual_edges_are_a_real_cycle():
    payload = _payload()
    payload.prerequisites = [("a", "b"), ("b", "a")]
    with pytest.raises(SchemaInvalidError, match="chu trình"):
        pedagogy.normalize_curriculum(payload)


def test_curriculum_unknown_edge_target_is_rejected():
    payload = _payload()
    payload.prerequisites = [("a", "ghost")]
    with pytest.raises(SchemaInvalidError, match="không tồn tại"):
        pedagogy.validate_curriculum(payload)


def test_curriculum_summary_returns_topological_order():
    payload = validate_proposal(_payload())
    summary = pedagogy.curriculum_summary(payload)
    assert summary["skillCount"] == 3
    assert summary["edgeCount"] == 2
    assert summary["topologicalOrder"] == ["a", "b", "c"]
    assert summary["highestBloomLevel"] == "analyze"


# ---------- lesson lint (P2.1) ----------


def test_lesson_rejects_duplicate_questions():
    content = LessonContent(
        title="t",
        blocks=[
            TeachBlock(type="teach", title="T", paragraphs=["Đoạn giảng có nội dung."]),
            {"type": "mc", "question": "Câu hỏi?", "options": ["a", "b"], "answerIndex": 0},
            {"type": "short", "question": "Câu hỏi?", "acceptedAnswers": ["x"]},
        ],
    )
    with pytest.raises(SchemaInvalidError, match="lặp"):
        validate_lesson(content)


def test_lesson_rejects_repeated_teach_paragraphs():
    repeated = "Đây là một đoạn giảng đủ dài để bị coi là trùng lặp nội dung."
    content = LessonContent(
        title="t",
        blocks=[
            TeachBlock(type="teach", title="T1", paragraphs=[repeated]),
            TeachBlock(type="teach", title="T2", paragraphs=[repeated]),
            {"type": "mc", "question": "Q?", "options": ["a", "b"], "answerIndex": 1},
        ],
    )
    with pytest.raises(SchemaInvalidError, match="lặp"):
        validate_lesson(content)


# ---------- provider + API integration ----------


@pytest.mark.asyncio
async def test_mock_proposal_is_valid_curriculum():
    provider = MockProvider()
    payload = await provider.generate_proposal("Python", ["q"] * 5, ["a"] * 5)
    payload.learnerProfile = pedagogy.extract_learner_profile(["q"] * 5, ["a"] * 5)
    payload = pedagogy.normalize_curriculum(payload)
    validated = pedagogy.validate_curriculum(payload)
    summary = pedagogy.curriculum_summary(validated)
    assert summary["skillCount"] == len(pedagogy.lesson_order(validated))
    assert summary["topologicalOrder"][0] != summary["topologicalOrder"][-1]


@pytest.mark.asyncio
async def test_api_proposal_exposes_profile_and_curriculum(client):
    email = f"p21-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = await client.post(
        "/v1/courses",
        json={"topic": "Python cho người mới", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    course_id = r.json()["id"]
    answers = [
        "Mình chưa từng học Python",
        "Muốn tự làm được một web app nhỏ",
        "Mỗi tuần 3 giờ",
        "Thích thực hành và làm dự án",
        "Muốn đi sâu backend",
    ]
    for i, answer in enumerate(answers):
        ra = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": answer},
            headers=csrf_headers(client),
        )
        assert ra.status_code == 200, ra.text

    rp = await client.get(f"/v1/courses/{course_id}/proposal")
    assert rp.status_code == 200, rp.text
    payload = rp.json()["payload"]

    profile = payload["learnerProfile"]
    assert profile["currentLevel"] == "beginner"
    assert profile["weeklyMinutes"] == 180
    assert profile["depth"] == "deep"

    lessons = [t for u in payload["units"] for t in u["lessonTitles"]]
    assert [s["lesson"] for s in payload["skills"]] == lessons
    assert payload["prerequisites"], "phải có cạnh prerequisite cho lộ trình tuyến tính"
    validated = pedagogy.validate_curriculum(ProposalPayload.model_validate(payload))
    assert pedagogy.curriculum_summary(validated)["topologicalOrder"]

    async with SessionLocal() as db:
        stored = (
            await db.execute(
                select(CourseProposal).where(CourseProposal.course_id == uuid.UUID(course_id[4:]))
            )
        ).scalars().first()
    assert stored.payload["learnerProfile"]["weeklyMinutes"] == 180

    # Approve → generation dùng curriculum snapshot; bài học vẫn sinh đủ.
    ra = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert ra.status_code == 202, ra.text
    for _ in range(200):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    assert rg.json()["status"] == "ready", rg.text

    detail = (await client.get(f"/v1/courses/{course_id}")).json()
    generated = [l["title"] for u in detail["units"] for l in u["lessons"]]
    assert generated == lessons


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", EVAL_TOPICS)
async def test_offline_topic_eval_schema_and_curriculum(topic):
    """Eval offline 10 topic: schema + DAG + lesson lint ổn định với mock.

    Đây là **deterministic** eval (mock), không phải đo chất lượng AI thật.
    """
    provider = MockProvider()
    questions = await provider.generate_interview_questions(topic)
    answers = [
        "Mình chưa từng học",
        f"Mục tiêu là áp dụng {topic} vào dự án cá nhân",
        "3 giờ mỗi tuần",
        "Thích thực hành",
        "Muốn đi sâu",
    ]
    payload = await provider.generate_proposal(topic, questions, answers)
    payload.learnerProfile = pedagogy.extract_learner_profile(questions, answers)
    payload = pedagogy.normalize_curriculum(payload)
    validated = pedagogy.validate_curriculum(payload)

    assert len(pedagogy.lesson_order(validated)) >= 2
    summary = pedagogy.curriculum_summary(validated)
    assert summary["skillCount"] == len(pedagogy.lesson_order(validated))

    for unit in validated.units:
        for title in unit.lessonTitles:
            lesson = await provider.generate_lesson(topic, validated, unit.title, title, [])
            validated_lesson = validate_lesson(lesson)
            assert any(b.type == "teach" for b in validated_lesson.blocks)
            assert any(b.type != "teach" for b in validated_lesson.blocks)
