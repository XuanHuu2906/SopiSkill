"""MockProvider — deterministic, không network, không phải AI thật.

Dùng cho dev/test và acceptance E2E. Nội dung sinh theo template bám topic
để luồng nghiệp vụ giống hệt khi thay bằng provider thật.
"""

import hashlib
from collections.abc import AsyncIterator

from app.providers.base import LLMProvider
from app.schemas.schemas import (
    BlankBlock,
    CurriculumSkill,
    LessonContent,
    MatchBlock,
    MCBlock,
    OrderBlock,
    ProposalPayload,
    ProposalUnit,
    ShortBlock,
    SourceContextEntry,
    TeachBlock,
)

INTERVIEW_QUESTIONS = [
    "Bạn đã từng tiếp xúc với {topic} chưa, và ở mức nào?",
    "Mục tiêu của bạn khi học {topic} là gì?",
    "Bạn dành được bao nhiêu thời gian mỗi tuần cho việc học {topic}?",
    "Kiểu học nào hiệu quả với bạn khi học {topic}: ví dụ thực hành, lý thuyết, hay dự án?",
    "Với {topic}, bạn muốn khóa học đi sâu hay phủ rộng kiến thức?",
]

LEVEL_WORDS = ["cơ bản", "nền tảng", "thực hành", "nâng cao", "chuyên sâu"]


def _hash_int(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)


class MockProvider(LLMProvider):
    name = "mock"

    async def generate_interview_questions(self, topic: str) -> list[str]:
        return [q.format(topic=topic) for q in INTERVIEW_QUESTIONS]

    async def generate_proposal(
        self, topic: str, interview_questions: list[str], interview_answers: list[str]
    ) -> ProposalPayload:
        seed = _hash_int(topic)
        focus = LEVEL_WORDS[seed % len(LEVEL_WORDS)]
        answer_digest = " ".join(a[:40] for a in interview_answers if a).strip() or "người mới"
        units = [
            ProposalUnit(
                title=f"Unit 1 — Nền tảng {topic}",
                blurb=f"Các khái niệm đầu tiên và thiết yếu của {topic}.",
                lessonTitles=[
                    f"{topic} là gì?",
                    f"Thiết lập môi trường cho {topic}",
                ],
            ),
            ProposalUnit(
                title=f"Unit 2 — Thực hành {topic}",
                blurb=f"Áp dụng {topic} qua ví dụ và bài tập.",
                lessonTitles=[
                    f"Bài tập đầu tiên với {topic}",
                    f"Lỗi thường gặp khi học {topic}",
                ],
            ),
        ]
        titles = [title for unit in units for title in unit.lessonTitles]
        bloom = ["understand", "apply", "apply", "analyze"]
        skills = [
            CurriculumSkill(
                id=f"sk-{index + 1}",
                title=title,
                lesson=title,
                bloomLevel=bloom[min(index, len(bloom) - 1)],
                outcome=f"Áp dụng được nội dung '{title}' khi học {topic}.",
            )
            for index, title in enumerate(titles)
        ]
        # Chuỗi prerequisite tuyến tính theo thứ tự bài — DAG hợp lệ, không chu trình.
        prerequisites = [
            (skills[index].id, skills[index + 1].id) for index in range(len(skills) - 1)
        ]
        return ProposalPayload(
            name=f"{topic}: lộ trình {focus}",
            objective=f"Giúp bạn ({answer_digest[:200]}) nắm vững {topic} ở mức {focus}.",
            units=units,
            outcomes=[
                f"Giải thích được các khái niệm {focus} của {topic}",
                f"Tự hoàn thành một ví dụ thực hành nhỏ với {topic}",
            ],
            skills=skills,
            prerequisites=prerequisites,
        )

    async def generate_lesson(
        self,
        topic: str,
        proposal: ProposalPayload,
        unit_title: str,
        lesson_title: str,
        previous_titles: list[str],
        source_context: list[SourceContextEntry] | None = None,
    ) -> LessonContent:
        seed = _hash_int(lesson_title)
        key_term = lesson_title.split("—")[-1].strip()

        # Nguồn chỉ ảnh hưởng phần diễn đạt, KHÔNG sinh citation/URL — server là
        # bên duy nhất tạo citation từ registry.
        source_line = (
            f"Tham khảo nguồn: {source_context[0].title}."
            if source_context
            else ""
        )

        teach: TeachBlock = {
            "type": "teach",
            "title": lesson_title,
            "paragraphs": [
                f"{key_term} là một trong những nội dung cốt lõi khi học {topic}.",
                f"Trong unit '{unit_title}', bạn sẽ làm quen từng bước qua ví dụ cụ thể.",
                "Hãy đọc kỹ đoạn dưới đây trước khi làm phần kiểm tra.",
                *([source_line] if source_line else []),
            ],
        }

        mc = MCBlock(
            type="mc",
            question=f"Câu nào mô tả đúng nhất về {key_term}?",
            options=[
                f"Một nội dung cốt lõi của {topic}",
                "Một phần mềm độc hại",
                "Một loại phần cứng",
                "Không liên quan đến {0}".format(topic),
            ],
            answerIndex=0 if seed % 2 == 0 else 1,
        )
        mc.options = _rotate_options(mc.options, mc.answerIndex, seed)
        mc.answerIndex = mc.options.index(
            f"Một nội dung cốt lõi của {topic}"
        ) if f"Một nội dung cốt lõi của {topic}" in mc.options else mc.answerIndex

        blank = BlankBlock(
            type="blank",
            sentence=f"Điền vào chỗ trống: Tôi đang học ____ .",
            answer=topic,
        )

        order = OrderBlock(
            type="order",
            prompt="Sắp xếp các bước học đúng thứ tự",
            items=["Đọc lý thuyết", "Làm ví dụ", "Kiểm tra", "Ôn tập"],
        )

        match = MatchBlock(
            type="match",
            prompt="Nối khái niệm với mô tả",
            pairs=[
                ("Lý thuyết", "Kiến thức nền"),
                ("Thực hành", "Áp dụng làm"),
                ("Ôn tập", "Củng cố lại"),
            ],
        )

        short = ShortBlock(
            type="short",
            question=f"Bạn đang học chủ đề nào? (trả lời ngắn)",
            acceptedAnswers=[topic.lower()],
        )

        return LessonContent(
            title=lesson_title,
            blocks=[teach, mc, blank, order, match, short],
        )

    async def plan_tutor_tool(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        available_tools: list[str],
        max_input_chars: int,
    ) -> dict:
        """Planner deterministic: chỉ gợi ý tool khi câu hỏi thật sự cần ngữ cảnh.

        Không phải AI: quy tắc keyword rõ ràng, mục tiêu là đường đi tool-loop
        có dữ liệu kiểm thử mà không cần network/chi phí. Chỉ trả tên tool nằm
        trong `available_tools`; nếu không thì `{"tool": None}`.
        """
        question = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                question = str(message.get("content", "")).casefold()
                break
        if "explain_deeper" in available_tools and any(
            phrase in question
            for phrase in ("giải thích sâu", "sâu hơn", "kỹ hơn", "chi tiết hơn")
        ):
            return {"tool": "explain_deeper", "args": {"blockIndex": 0}}
        if "read_lesson" in available_tools and any(
            phrase in question
            for phrase in ("đọc lại", "toàn bộ bài", "cả bài", "nội dung bài")
        ):
            return {"tool": "read_lesson", "args": {}}
        if "read_source" in available_tools and any(
            phrase in question for phrase in ("nguồn", "tài liệu", "trích dẫn")
        ):
            return {"tool": "read_source", "args": {}}
        return {"tool": None, "args": {}}

    async def stream_tutor_reply(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_input_chars: int,
    ) -> AsyncIterator[str]:
        """Stream deterministic — KHÔNG phải AI thật, dùng cho test/dev.

        Nội dung bám câu hỏi cuối + tên bài để luồng UI/SSE có dữ liệu thật để
        kiểm tra ordering, nhưng không tuyên bố đây là câu trả lời của model.
        """
        question = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                question = " ".join(str(message.get("content", "")).split())[:300]
                break
        lesson_line = next(
            (line for line in system.splitlines() if line.startswith("Bài học hiện tại:")),
            "",
        )
        answer = (
            "Mình là trợ giảng ở chế độ MOCK (không phải AI thật). "
            f"{lesson_line.strip()} Câu hỏi của bạn: \"{question}\". "
            "Gợi ý: hãy đọc lại đoạn giảng ngay trên block bạn đang mở, "
            "rồi tự giải thích bằng lời của mình trước khi xem đáp án quiz. "
            "Mình chưa có nguồn tài liệu được kiểm chứng để trích dẫn."
        )
        # Chia theo từ để mỗi delta có ý nghĩa; không sleep để test nhanh.
        words = answer.split(" ")
        for index, word in enumerate(words):
            yield word if index == 0 else " " + word



def _rotate_options(options: list[str], answer_index: int, seed: int) -> list[str]:
    """Xoay vị trí đáp án đúng để mock không đoán được theo index."""
    correct = options[answer_index]
    shift = seed % len(options)
    rotated = options[shift:] + options[:shift]
    return rotated if correct in rotated else options
