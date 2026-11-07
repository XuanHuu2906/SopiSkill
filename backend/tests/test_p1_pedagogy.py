"""P1-PEDAGOGY — regression cho việc trích hồ sơ người học (deterministic, không LLM).

Bảng dưới đây gồm các câu trả lời thật người học Việt hay gõ: có dấu, không dấu,
viết tắt, khoảng thời gian, cách nói tự nhiên, và câu thật sự mơ hồ. Mục tiêu là
khoá hành vi đã sai (60× thấp hơn, None, balanced, []) và khoá luôn các trường
hợp đang đúng để không regress.

Không test nào gọi mạng hay provider trả phí.
"""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import CourseProposal, GenerationJob
from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.services import pedagogy
from tests.support import correct_answers

PASSWORD = "Passw0rd!123"

VALID_PROPOSAL = {
    "name": "Python căn bản",
    "objective": "Nắm cú pháp và viết được script nhỏ.",
    "units": [
        {"title": "Nền tảng", "blurb": "Cú pháp", "lessonTitles": ["Biến", "Kiểu dữ liệu"]},
        {"title": "Thực hành", "blurb": "Bài tập", "lessonTitles": ["Vòng lặp", "Hàm"]},
    ],
    "outcomes": ["Viết được script CLI", "Giải thích được kiểu dữ liệu"],
    "skills": [
        {"id": "s0", "title": "Biến", "lesson": "Biến", "bloomLevel": "understand", "outcome": "Hiểu Biến"},
        {"id": "s1", "title": "Kiểu dữ liệu", "lesson": "Kiểu dữ liệu", "bloomLevel": "understand", "outcome": "Hiểu Kiểu dữ liệu"},
        {"id": "s2", "title": "Vòng lặp", "lesson": "Vòng lặp", "bloomLevel": "understand", "outcome": "Hiểu Vòng lặp"},
        {"id": "s3", "title": "Hàm", "lesson": "Hàm", "bloomLevel": "understand", "outcome": "Hiểu Hàm"},
    ],
    "prerequisites": [["s0", "s1"], ["s1", "s2"], ["s2", "s3"]],
}


def _profile(*answers: str):
    return pedagogy.extract_learner_profile([f"q{i}" for i in range(len(answers))], list(answers))


def csrf_headers(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


# ---------- thời gian/tuần ----------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        # 4 case bắt buộc theo gate
        ("3 gio tuan", 180),
        ("3 gio/tuan", 180),
        ("2 tieng/tuan", 120),
        ("90 phut", 90),
        # có dấu — chống regress
        ("Mỗi tuần mình dành 3 giờ", 180),
        ("2 tiếng/tuần", 120),
        ("90 phút", 90),
        ("45 phút mỗi tuần", 45),
        # viết tắt / khoảng / thập phân
        ("5-6h mỗi tuần", 300),
        ("3-4 giờ mỗi tuần", 180),
        ("1,5 giờ mỗi tuần", 90),
        ("10 hours per week", 600),
        # không dấu, cách nói tự nhiên
        ("3 gio moi tuan", 180),
        ("hoc khoang 2 tieng moi tuan", 120),
        ("2 tieng moi tuan", 120),
        ("45 phut moi tuan", 45),
    ],
)
def test_weekly_minutes_table(answer: str, expected: int):
    assert _profile(answer).weeklyMinutes == expected


def test_weekly_minutes_is_none_when_no_unit():
    """Không có đơn vị thời gian thì không được đoán."""
    assert _profile("mình học rất chăm").weeklyMinutes is None
    assert _profile("tuần nào cũng học").weeklyMinutes is None


def test_bare_letter_h_inside_a_word_is_not_an_hour():
    """`h` nằm trong một từ khác không được hiểu là 'giờ'."""
    assert pedagogy._parse_weekly_minutes("mình đang ở tầng 4th") is None
    assert pedagogy._parse_weekly_minutes("học lớp 4th") is None


# ---------- độ sâu ----------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        # bắt buộc
        ("mình muốn hiểu sâu", "deep"),
        ("hiểu sâu để áp dụng", "deep"),
        # không dấu
        ("minh muon hieu sau", "deep"),
        ("hieu sau de ap dung", "deep"),
        # có dấu — chống regress
        ("đi sâu vào chi tiết", "deep"),
        ("mình muốn học chuyên sâu", "deep"),
        ("phủ rộng kiến thức", "broad"),
        ("mình cần tổng quan", "broad"),
        # không dấu
        ("phu rong kien thuc", "broad"),
        ("can tong quan", "broad"),
        # không tín hiệu
        ("mình chưa rõ", "balanced"),
    ],
)
def test_depth_table(answer: str, expected: str):
    assert _profile(answer).depth == expected


def test_unaccented_sau_after_is_not_depth():
    """`sau` (after) và `trong` (in/during) là từ chức năng, không phải độ sâu."""
    assert _profile("minh hoc sau khi di lam").depth == "balanced"
    assert _profile("minh hoc 3 gio trong tuan").depth == "balanced"


def test_conflicting_depth_warns_instead_of_guessing():
    profile = _profile("mình vừa muốn phủ rộng vừa muốn hiểu sâu")
    assert profile.depth == "balanced"
    assert any("sâu" in w.casefold() and "rộng" in w.casefold() for w in profile.warnings)


# ---------- phong cách học ----------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        # bắt buộc
        ("đồ thị và ví dụ thực tế", ["hands_on", "visual"]),
        ("do thi va vi du thuc te", ["hands_on", "visual"]),
        # có dấu — chống regress
        ("học qua sơ đồ trực quan", ["visual"]),
        ("làm ví dụ và bài tập", ["hands_on"]),
        ("thích lý thuyết", ["theory"]),
        ("làm dự án thật", ["project"]),
        ("thực hành và làm dự án", ["hands_on", "project"]),
        # không dấu
        ("hoc qua so do truc quan", ["visual"]),
        ("lam vi du va bai tap", ["hands_on"]),
        ("thich ly thuyet", ["theory"]),
    ],
)
def test_styles_table(answer: str, expected: list[str]):
    assert _profile(answer).preferredStyles == expected


# ---------- trình độ ----------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Mình chưa từng học Python", "beginner"),
        ("minh chua biet gi ve python", "beginner"),
        ("Mình đã học qua rồi", "intermediate"),
        ("minh da hoc qua roi", "intermediate"),
        ("Mình đã có nhiều năm kinh nghiệm", "advanced"),
        ("minh da co nhieu nam kinh nghiem", "advanced"),
    ],
)
def test_level_table(answer: str, expected: str):
    assert _profile(answer).currentLevel == expected


def test_level_conflict_still_warns():
    profile = _profile("Mình mới bắt đầu nhưng cũng muốn học nâng cao")
    assert profile.currentLevel == "intermediate"
    assert any("trung bình" in w for w in profile.warnings)


# ---------- không suy diễn thuộc tính nhạy cảm ----------


def test_profile_does_not_infer_sensitive_attributes():
    profile = _profile("Mình 22 tuổi, nữ", "mục tiêu là đi làm", "4h", "thực hành", "hiểu sâu")
    dumped = profile.model_dump()
    assert "age" not in dumped and "gender" not in dumped
    assert dumped["weeklyMinutes"] == 240


# ---------- pass-through: API → DB → job ----------


async def _register(client, prefix: str) -> str:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


async def _course_with_answers(client, topic: str, answers: list[str]) -> str:
    r = await client.post(
        "/v1/courses",
        json={"topic": topic, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    course_id = r.json()["id"]
    for i, answer in enumerate(answers):
        ra = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": answer},
            headers=csrf_headers(client),
        )
        assert ra.status_code == 200, ra.text
    return course_id


UNACCENTED_ANSWERS = [
    "Minh chua biet gi ve Python",
    "Muon tu lam duoc mot web app nho",
    "Moi tuan minh danh 3 gio",
    "Thich hoc qua do thi va vi du thuc te",
    "Minh muon hieu sau",
]


@pytest.mark.asyncio
async def test_api_proposal_receives_parsed_profile(client):
    """Hồ sơ phải đúng ở payload API — không chỉ đúng khi gọi hàm riêng lẻ."""
    await _register(client, "p1ped-api")
    course_id = await _course_with_answers(client, "Python cho người mới", UNACCENTED_ANSWERS)

    rp = await client.get(f"/v1/courses/{course_id}/proposal")
    assert rp.status_code == 200, rp.text
    profile = rp.json()["payload"]["learnerProfile"]

    assert profile["currentLevel"] == "beginner"
    assert profile["weeklyMinutes"] == 180
    assert profile["depth"] == "deep"
    assert profile["preferredStyles"] == ["hands_on", "visual"]

    # Lưu bền: đọc thẳng DB, không tin response.
    async with SessionLocal() as db:
        stored = (
            await db.execute(
                select(CourseProposal).where(CourseProposal.course_id == uuid.UUID(course_id[4:]))
            )
        ).scalars().first()
    assert stored is not None
    assert stored.payload["learnerProfile"]["weeklyMinutes"] == 180
    assert stored.payload["learnerProfile"]["depth"] == "deep"


@pytest.mark.asyncio
async def test_generation_pins_same_proposal_containing_profile(client):
    """Job generation phải pin đúng proposal version chứa hồ sơ đã sửa."""
    await _register(client, "p1ped-gen")
    course_id = await _course_with_answers(client, "Python cho người mới", UNACCENTED_ANSWERS)

    rp = await client.get(f"/v1/courses/{course_id}/proposal")
    version = rp.json()["version"]

    ra = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert ra.status_code == 202, ra.text

    rg = None
    for _ in range(200):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    assert rg.json()["status"] == "ready", rg.text

    async with SessionLocal() as db:
        job = (
            await db.execute(
                select(GenerationJob).where(GenerationJob.course_id == uuid.UUID(course_id[4:]))
            )
        ).scalars().first()
    assert job is not None
    assert job.proposal_version == version
    assert job.status.value == "ready"


@pytest.mark.asyncio
async def test_full_chain_from_unaccented_answers_to_quiz(client):
    """Chuỗi đầy đủ: topic → interview → profile → proposal → generation → lesson → quiz.

    Khác với các test trên, test này chứng minh hồ sơ suy ra từ câu trả lời
    **không dấu** không chỉ đúng khi gọi parser riêng lẻ mà còn đi hết được
    pipeline sinh bài và chấm điểm.
    """
    await _register(client, "p1ped-chain")
    course_id = await _course_with_answers(client, "Python cho người mới", UNACCENTED_ANSWERS)

    proposal = (await client.get(f"/v1/courses/{course_id}/proposal")).json()
    profile = proposal["payload"]["learnerProfile"]
    assert profile["weeklyMinutes"] == 180
    assert profile["depth"] == "deep"
    assert profile["preferredStyles"] == ["hands_on", "visual"]
    assert profile["currentLevel"] == "beginner"

    ra = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert ra.status_code == 202, ra.text

    status = None
    for _ in range(200):
        await asyncio.sleep(0.05)
        status = (await client.get(f"/v1/courses/{course_id}/generation")).json()["status"]
        if status in ("ready", "failed"):
            break
    assert status == "ready"

    detail = (await client.get(f"/v1/courses/{course_id}")).json()
    lessons = [lesson for unit in detail["units"] for lesson in unit["lessons"]]
    assert lessons, "generation phải tạo ra ít nhất một bài"

    lesson_id = lessons[0]["id"]
    lesson = (await client.get(f"/v1/lessons/{lesson_id}")).json()
    for block in lesson["blocks"]:
        assert "answerIndex" not in block
        assert "answer" not in block
        assert "acceptedAnswers" not in block
        assert "pairs" not in block

    version, answers = await correct_answers(lesson_id)
    assert version == lesson["contentVersion"]
    attempt = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        json={
            "clientAttemptId": uuid.uuid4().hex[:16],
            "contentVersion": version,
            "durationMs": 30000,
            "answers": answers,
        },
        headers=csrf_headers(client),
    )
    assert attempt.status_code == 201, attempt.text
    assert attempt.json()["score"]["total"] > 0
    assert attempt.json()["score"]["correct"] == attempt.json()["score"]["total"]


# ---------- pass-through: prompt provider thật (không gọi mạng) ----------


@pytest.mark.asyncio
async def test_provider_prompt_carries_corrected_profile():
    """Prompt gửi provider thật phải mang hồ sơ đã sửa, không phải bản sai."""
    import json as _json

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["user"] = _json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": _json.dumps(VALID_PROPOSAL)}}
                ],
                "usage": {"prompt_tokens": 42, "completion_tokens": 128},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="sk-test-not-real",
        base_url="https://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    await provider.generate_proposal(
        "Python cho người mới", [f"q{i}" for i in range(5)], UNACCENTED_ANSWERS
    )

    line = captured["user"]
    assert "Hồ sơ tóm tắt" in line
    assert "180" in line
    assert "deep" in line
    assert "visual" in line and "hands_on" in line


# ---------- bảo mật: hồ sơ không rò sang user khác ----------


@pytest.mark.asyncio
async def test_cross_user_cannot_read_proposal_profile(client):
    await _register(client, "p1ped-a")
    course_id = await _course_with_answers(client, "Python của A", UNACCENTED_ANSWERS)
    assert (await client.get(f"/v1/courses/{course_id}/proposal")).status_code == 200

    await _register(client, "p1ped-b")
    r = await client.get(f"/v1/courses/{course_id}/proposal")
    assert r.status_code == 404, r.text
