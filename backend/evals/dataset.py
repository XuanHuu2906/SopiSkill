"""P2.2 eval dataset — >= 12 topic, đa dạng ngôn ngữ/trình độ/độ mơ hồ.

**Không** chứa tài liệu riêng chưa được phép. Mỗi case có:

  - `id`, `topic`, `language` (`vi` | `en`);
  - `level` (`beginner` | `intermediate` | `advanced`);
  - `ambiguity` (`clear` | `broad` | `ambiguous`) — chủ đề mơ hồ phải khiến hệ
    thống thu hẹp phạm vi, không được bịa nội dung chuyên sâu;
  - `answers`: đúng 5 câu trả lời phỏng vấn (dùng cho cả mock và real);
  - `expect`: kỳ vọng **cấu trúc** (không so khớp chuỗi tự do):
      · `minLessons` / `maxLessons`
      · `requireTeachAndQuiz` (luôn true)
      · `minQuizPerLesson`
  - `tags`: nhãn để lọc nhanh (tech/social/language/science…).

Expected properties, not brittle strings: eval không chấm "câu này phải viết
đúng chữ này". Chất lượng sư phạm chấm bằng rubric (người hoặc LLM-as-judge có
metadata), và kết quả judge KHÔNG được coi là ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    id: str
    topic: str
    language: str
    level: str
    ambiguity: str
    answers: tuple[str, ...]
    min_lessons: int = 4
    max_lessons: int = 12
    min_quiz_per_lesson: int = 1
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "language": self.language,
            "level": self.level,
            "ambiguity": self.ambiguity,
            "answers": list(self.answers),
            "expect": {
                "minLessons": self.min_lessons,
                "maxLessons": self.max_lessons,
                "requireTeachAndQuiz": True,
                "minQuizPerLesson": self.min_quiz_per_lesson,
            },
            "tags": list(self.tags),
        }


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="vi-beginner-python",
        topic="Python cho người mới bắt đầu",
        language="vi",
        level="beginner",
        ambiguity="clear",
        answers=(
            "Mình chưa từng học Python",
            "Muốn tự viết script xử lý file Excel cho công việc",
            "Mỗi tuần khoảng 4 giờ",
            "Thích thực hành và làm bài tập nhỏ",
            "Muốn nắm nền tảng thật chắc trước khi đi sâu",
        ),
        tags=("tech", "programming"),
    ),
    EvalCase(
        id="vi-intermediate-sql",
        topic="Tối ưu truy vấn SQL cho ứng dụng web",
        language="vi",
        level="intermediate",
        ambiguity="clear",
        answers=(
            "Mình đã viết SQL được khoảng 2 năm",
            "Muốn giảm thời gian tải báo cáo từ vài phút xuống vài giây",
            "3 giờ mỗi tuần",
            "Thích phân tích execution plan và thử trên dữ liệu mẫu",
            "Đi sâu vào index và cách đọc query plan",
        ),
        tags=("tech", "database"),
    ),
    EvalCase(
        id="vi-advanced-behavioural-econ",
        topic="Kinh tế học hành vi ứng dụng trong thiết kế sản phẩm",
        language="vi",
        level="advanced",
        ambiguity="broad",
        answers=(
            "Mình đã có nhiều năm kinh nghiệm làm product",
            "Muốn áp dụng thiên lệch nhận thức vào onboarding để tăng retention",
            "2 giờ mỗi tuần",
            "Thích đọc nghiên cứu kèm ví dụ thực tế",
            "Muốn đi sâu vào các mô hình và bằng chứng",
        ),
        tags=("social", "product"),
    ),
    EvalCase(
        id="vi-beginner-cooking",
        topic="Nấu ăn cơ bản cho sinh viên ở trọ",
        language="vi",
        level="beginner",
        ambiguity="clear",
        answers=(
            "Mình gần như không biết nấu",
            "Muốn tự nấu 5 món đơn giản trong tuần",
            "Khoảng 3 giờ mỗi tuần",
            "Thích làm theo công thức có hình",
            "Chỉ cần đủ dùng, không đi sâu kỹ thuật nhà hàng",
        ),
        tags=("life", "skill"),
    ),
    EvalCase(
        id="vi-ambiguous-ai",
        topic="AI",
        language="vi",
        level="beginner",
        ambiguity="ambiguous",
        answers=(
            "Mình mới nghe nói về AI, chưa học gì",
            "Muốn hiểu AI là gì và dùng được vài công cụ trong công việc",
            "2 giờ mỗi tuần",
            "Thích ví dụ thực tế hơn công thức toán",
            "Muốn phủ rộng trước, chưa cần đi sâu",
        ),
        tags=("ambiguous", "tech"),
    ),
    EvalCase(
        id="vi-advanced-statistics",
        topic="Thống kê suy luận cho nghiên cứu y sinh",
        language="vi",
        level="advanced",
        ambiguity="clear",
        answers=(
            "Mình đã học xác suất cơ bản và dùng SPSS",
            "Muốn tự chọn đúng kiểm định cho từng thiết kế nghiên cứu",
            "5 giờ mỗi tuần",
            "Thích bài tập có dữ liệu thật và giải thích giả định",
            "Đi sâu vào giả định, power analysis và cách báo cáo",
        ),
        tags=("science", "statistics"),
    ),
    EvalCase(
        id="en-beginner-excel",
        topic="Excel for absolute beginners",
        language="en",
        level="beginner",
        ambiguity="clear",
        answers=(
            "I have never used Excel beyond opening a file",
            "I want to build a simple budget tracker for myself",
            "about 2 hours per week",
            "I learn best by following short hands-on steps",
            "I just need practical basics, not expert formulas",
        ),
        tags=("tech", "office"),
    ),
    EvalCase(
        id="en-intermediate-writing",
        topic="Academic writing for ESL graduate students",
        language="en",
        level="intermediate",
        ambiguity="clear",
        answers=(
            "I can write essays but struggle with academic tone",
            "I need to write a literature review chapter",
            "4 hours per week",
            "I prefer examples and feedback on my drafts",
            "I want to go deep into structure and citation",
        ),
        tags=("language", "writing"),
    ),
    EvalCase(
        id="en-advanced-distributed",
        topic="Distributed systems consistency models",
        language="en",
        level="advanced",
        ambiguity="clear",
        answers=(
            "I have several years of backend experience with highly available services",
            "I want to reason correctly about trade-offs when designing a new data store",
            "about 5 hours per week",
            "hands-on with failure scenarios and code labs",
            "deep dive into proofs and real production incidents",
        ),
        tags=("tech", "systems"),
    ),
    EvalCase(
        id="en-beginner-guitar",
        topic="Guitar basics for adults starting from zero",
        language="en",
        level="beginner",
        ambiguity="clear",
        answers=(
            "I have never played any instrument",
            "I want to play a few songs for friends within three months",
            "20 minutes a day",
            "I prefer watching then repeating slowly",
            "balanced: chords and rhythm, not music theory deep dive",
        ),
        tags=("arts", "music"),
    ),
    EvalCase(
        id="en-ambiguous-productivity",
        topic="Productivity",
        language="en",
        level="intermediate",
        ambiguity="ambiguous",
        answers=(
            "I read a lot about productivity but rarely stick to a system",
            "I want to finish my side projects without burning out",
            "3 hours per week",
            "I like short actionable experiments",
            "broad overview first, then pick one method",
        ),
        tags=("ambiguous", "self-improvement"),
    ),
    EvalCase(
        id="en-advanced-climate",
        topic="Climate policy evaluation methods",
        language="en",
        level="advanced",
        ambiguity="broad",
        answers=(
            "I work in public policy and know basic economics",
            "I want to critique cost-benefit analyses of carbon pricing",
            "6 hours per week",
            "I prefer case studies and data interpretation",
            "deep dive into modelling assumptions and uncertainty",
        ),
        tags=("social", "policy"),
    ),
)


def get_cases(ids: list[str] | None = None, limit: int | None = None) -> list[EvalCase]:
    cases = list(EVAL_CASES)
    if ids:
        wanted = {i.strip() for i in ids if i.strip()}
        unknown = wanted - {c.id for c in cases}
        if unknown:
            raise ValueError(f"Topic id không tồn tại: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in wanted]
    if limit is not None:
        cases = cases[: max(0, limit)]
    return cases


def dataset_summary(cases: list[EvalCase] | None = None) -> dict:
    cases = list(cases if cases is not None else EVAL_CASES)
    return {
        "topics": len(cases),
        "languages": sorted({c.language for c in cases}),
        "levels": sorted({c.level for c in cases}),
        "ambiguity": sorted({c.ambiguity for c in cases}),
        "tags": sorted({tag for c in cases for tag in c.tags}),
    }
