"""Topic analysis (P2.SR) — deterministic, KHÔNG gọi LLM.

Vì sao không dùng LLM ở phase này: phân tích chủ đề chỉ cần tách tín hiệu có cấu
trúc (domain, từ khoá con, trình độ, ngôn ngữ). Dùng LLM ở đây sẽ (a) tạo chi phí
và độ trễ không cần thiết, (b) không kiểm thử offline được, (c) khiến output khó
giải thích. Khi cần suy luận sâu hơn, điểm nối là `analyze_topic` — không đổi
contract của agent.
"""

from __future__ import annotations

import re

from app.agents.source_research.policies import classify_domain, resolve_policy
from app.agents.source_research.schemas import MAX_TOPIC_LENGTH, ResearchRequest, TopicAnalysis

# Từ khoá → chủ đề con. Deterministic, phục vụ cả tiếng Việt (không dấu) và tiếng Anh.
_SUBTOPIC_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("python", "py"), "Python Basics"),
    (("data structure", "cấu trúc dữ liệu", "cau truc du lieu", "list", "dict"), "Data Structures"),
    (("function", "hàm", "module", "package"), "Functions and Modules"),
    (("lập trình", "lap trinh", "programming", "code", "từ con số 0", "tu con so 0"), "Programming Fundamentals"),
    (("numpy",), "NumPy"),
    (("pandas",), "Pandas"),
    (("machine learning", "học máy", "hoc may", "ml"), "Machine Learning Fundamentals"),
    (("deep learning", "học sâu", "hoc sau", "neural"), "Deep Learning Fundamentals"),
    (("ai", "trí tuệ nhân tạo", "tri tue nhan tao", "artificial intelligence"), "AI Application Development"),
    (("javascript", "typescript"), "JavaScript Fundamentals"),
    (("react", "next.js"), "React and Next.js"),
    (("sql", "database", "cơ sở dữ liệu", "co so du lieu"), "Database Fundamentals"),
    (("docker", "kubernetes"), "Container and Orchestration"),
    (("api", "backend", "rest"), "Backend API Design"),
    (("chẩn đoán", "chan doan", "diagnosis"), "Diagnostic Criteria"),
    (("điều trị", "dieu tri", "treatment"), "Treatment Guidelines"),
    (("tăng huyết áp", "tang huyet ap", "hypertension"), "Hypertension Management"),
    (("tiểu đường", "tieu duong", "diabetes"), "Diabetes Management"),
    (("dược", "duoc", "pharmacology", "thuốc", "thuoc"), "Pharmacology"),
)

_PREREQUISITE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("python", "javascript", "typescript", "lập trình", "lap trinh", "programming"), "Programming Fundamentals"),
    (("machine learning", "học máy", "hoc may", "deep learning", "ai"), "Mathematics for Machine Learning"),
    (("tăng huyết áp", "tang huyet ap", "tim mạch", "tim mach"), "Basic Physiology"),
    (("dược", "duoc", "pharmacology", "thuoc"), "Basic Pharmacology"),
)

_RECOMMENDATIONS: dict[str, tuple[str, ...]] = {
    "programming": (
        "official_documentation",
        "standard_specification",
        "university_course",
        "technical_book",
        "curated_reference",
    ),
    "medicine": (
        "clinical_guideline",
        "systematic_review",
        "government_health",
        "academic",
        "university_course",
    ),
    "general": (
        "official_documentation",
        "university_course",
        "technical_book",
        "educational_resource",
        "curated_reference",
    ),
}

_LEVEL_SIGNALS = {
    "beginner": (
        "từ con số 0", "tu con so 0", "từ đầu", "tu dau", "mới bắt đầu", "moi bat dau",
        "beginner", "cơ bản", "co ban", "nhập môn", "nhap mon", "zero",
    ),
    "advanced": (
        "nâng cao", "nang cao", "advanced", "expert", "chuyên sâu", "chuyen sau",
        "tối ưu", "toi uu", "kiến trúc", "kien truc",
    ),
    "intermediate": ("trung cấp", "trung cap", "intermediate", "đã biết", "da biet"),
}


def _detect_level(text: str, override: str | None) -> str:
    if override in ("beginner", "intermediate", "advanced"):
        return override
    for level in ("beginner", "advanced", "intermediate"):
        if any(signal in text for signal in _LEVEL_SIGNALS[level]):
            return level
    return "beginner"


def _detect_language(request: ResearchRequest) -> str:
    if request.preferredLanguage:
        return request.preferredLanguage.strip().lower()
    return "vi"


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    """So khớp có biên từ cho token ngắn (`ai`, `py`, `ml`) để tránh khớp nhầm
    trong 'mai', 'hai', 'chẩn đoán'...; các cụm dài dùng so khớp chuỗi con."""
    for needle in needles:
        if len(needle) <= 3 and needle.isalnum():
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text):
                return True
        elif needle in text:
            return True
    return False


def analyze_topic(request: ResearchRequest) -> TopicAnalysis:
    """Phân tích chủ đề thành domain, chủ đề con, tiên quyết, truy vấn tìm kiếm.

    Mọi kết quả đều tất định từ chính input; cùng input ⇒ cùng output.
    """
    topic = " ".join(request.topic.split())[:MAX_TOPIC_LENGTH]
    text = topic.casefold()
    domain = classify_domain(topic)

    sub_topics: list[str] = []
    for needles, label in _SUBTOPIC_RULES:
        if _contains_any(text, needles) and label not in sub_topics:
            sub_topics.append(label)

    # Python cho AI "từ con số 0" ngầm đòi hỏi nền tảng ngôn ngữ + toán/ML cơ bản.
    # Suy ra minh bạch từ tín hiệu có trong chủ đề (không bịa thêm nguồn).
    if "Python Basics" in sub_topics:
        for implied in ("Data Structures", "Functions and Modules"):
            if implied not in sub_topics:
                sub_topics.append(implied)
    if _contains_any(text, ("ai", "machine learning", "học máy", "hoc may", "trí tuệ nhân tạo")):
        for implied in ("NumPy", "Machine Learning Fundamentals"):
            if implied not in sub_topics:
                sub_topics.append(implied)
    # "Programming Fundamentals" luôn là nền của nhóm ngôn ngữ lập trình.
    if domain == "programming" and _contains_any(text, ("python", "javascript", "typescript", "java", "lập trình", "lap trinh")):
        if "Programming Fundamentals" not in sub_topics:
            sub_topics.insert(0, "Programming Fundamentals")

    prerequisites: list[str] = []
    for needles, label in _PREREQUISITE_RULES:
        if _contains_any(text, needles) and label not in prerequisites:
            prerequisites.append(label)

    domain = classify_domain(topic)
    domain = classify_domain(topic)
    policy = resolve_policy(domain)
    level = _detect_level(text, request.learnerLevel)

    recommended = list(_RECOMMENDATIONS.get(domain, _RECOMMENDATIONS["general"]))
    # Bỏ loại nguồn không có trong policy của domain để gợi ý luôn dùng được.
    recommended = [kind for kind in recommended if kind in policy.typePriority]
    notes: list[str] = [
        "Phân tích chủ đề là rule-based (keyword), không phải suy luận LLM.",
        "Không suy diễn thuộc tính nhạy cảm của người học.",
    ]
    if not sub_topics:
        notes.append("Không phát hiện chủ đề con cụ thể; sẽ tìm theo đúng chủ đề chính.")

    queries: list[str] = [topic]
    for sub in sub_topics[:3]:
        queries.append(f"{topic} {sub}"[:MAX_TOPIC_LENGTH])
    for kind in recommended[:2]:
        queries.append(f"{topic} {kind.replace('_', ' ')}"[:MAX_TOPIC_LENGTH])

    return TopicAnalysis(
        mainTopic=topic,
        domain=domain,
        subTopics=sub_topics[:12],
        prerequisites=prerequisites[:8],
        learnerLevel=level,
        language=_detect_language(request),
        learningGoals=list(request.learningGoals),
        recommendedSourceTypes=recommended[:8],
        searchQueries=queries[:4],
        notes=notes,
    )
