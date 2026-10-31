"""Domain trust policies (P2.SR).

Một "trust score" duy nhất cho mọi lĩnh vực là sai: nguồn chính thức của Python
không cùng loại uy tín với hướng dẫn lâm sàng. Vì vậy mỗi domain có bảng ưu tiên
loại nguồn riêng (`typePriority`) và trọng số tiêu chí riêng (`weights`).

Điểm số chỉ dùng để **xếp hạng trong một lần nghiên cứu**, không phải xác suất
nguồn đúng và không thay thế review của con người.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Domain = str


@dataclass(frozen=True)
class DomainPolicy:
    domain: str
    label: str
    description: str
    # Điểm [0,1] cho từng loại nguồn. Loại không có trong bảng ⇒ 0.15 (không bị
    # loại, nhưng luôn xếp sau) — vì loại lạ không đồng nghĩa nguồn xấu.
    typePriority: dict[str, float]
    weights: dict[str, float] = field(default_factory=dict)
    # Loại nguồn được coi là "chính thức" cho domain (dùng cho selectionReason).
    officialTypes: tuple[str, ...] = ()

    def priority_of(self, source_type: str) -> float:
        return self.typePriority.get(source_type, 0.15)


# Từ khoá phân loại domain. Deterministic, không dùng LLM.
_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "programming": (
        "python", "javascript", "typescript", "java", "golang", "rust", "c++", "c#",
        "sql", "lập trình", "lap trinh", "programming", "software", "web", "api",
        "react", "next.js", "docker", "kubernetes", "machine learning", "deep learning",
        "ai", "data science", "database", "backend", "frontend", "linux", "git",
    ),
    "medicine": (
        "y tế", "y te", "sức khỏe", "suc khoe", "bệnh", "benh", "chẩn đoán",
        "chan doan", "điều trị", "dieu tri", "tăng huyết áp", "tiểu đường",
        "medicine", "medical", "clinical", "diagnosis", "treatment", "disease",
        "pharmacology", "dược", "vaccine", "ung thư", "covid", "hội chứng",
    ),
}

PROGRAMMING_POLICY = DomainPolicy(
    domain="programming",
    label="Programming",
    description=(
        "Ưu tiên tài liệu chính thức và đặc tả kỹ thuật; tài liệu cộng đồng chỉ để bổ sung."
    ),
    typePriority={
        "official_documentation": 1.0,
        "standard_specification": 0.95,
        "university_course": 0.75,
        "technical_book": 0.68,
        "curated_reference": 0.6,
        "educational_resource": 0.55,
        "webpage": 0.35,
        "academic": 0.5,
        "community_tutorial": 0.3,
        "user_document": 0.4,
    },
    weights={
        "authority": 0.3,
        "relevance": 0.25,
        "freshness": 0.25,
        "metadataCompleteness": 0.2,
    },
    officialTypes=("official_documentation", "standard_specification"),
)

MEDICINE_POLICY = DomainPolicy(
    domain="medicine",
    label="Medicine",
    description=(
        "Ưu tiên hướng dẫn lâm sàng và tổng quan hệ thống; blog/community không đủ tin cậy."
    ),
    typePriority={
        "clinical_guideline": 1.0,
        "systematic_review": 0.95,
        "government_health": 0.9,
        "academic": 0.75,
        "university_course": 0.6,
        "technical_book": 0.5,
        "curated_reference": 0.45,
        "official_documentation": 0.5,
        "webpage": 0.2,
        "community_tutorial": 0.05,
        "user_document": 0.25,
    },
    weights={
        "authority": 0.4,
        "relevance": 0.25,
        "freshness": 0.25,
        "metadataCompleteness": 0.1,
    },
    officialTypes=("clinical_guideline", "systematic_review", "government_health"),
)

GENERAL_POLICY = DomainPolicy(
    domain="general",
    label="General education",
    description=(
        "Ưu tiên chương trình chính thức, sách học thuật và khóa học đại học."
    ),
    typePriority={
        "official_documentation": 0.85,
        "standard_specification": 0.8,
        "clinical_guideline": 0.85,
        "systematic_review": 0.8,
        "government_health": 0.8,
        "academic": 0.75,
        "university_course": 0.8,
        "technical_book": 0.72,
        "educational_resource": 0.65,
        "curated_reference": 0.6,
        "webpage": 0.35,
        "community_tutorial": 0.3,
        "user_document": 0.45,
    },
    weights={
        "authority": 0.3,
        "relevance": 0.25,
        "freshness": 0.2,
        "metadataCompleteness": 0.25,
    },
    officialTypes=("official_documentation", "university_course", "government_health"),
)

POLICIES: dict[str, DomainPolicy] = {
    "programming": PROGRAMMING_POLICY,
    "medicine": MEDICINE_POLICY,
    "general": GENERAL_POLICY,
}


def classify_domain(topic: str) -> str:
    """Phân loại domain bằng keyword deterministic (không LLM, không network)."""
    text = " ".join((topic or "").casefold().split())
    if not text:
        return "general"
    scores = {
        domain: sum(1 for word in words if word in text)
        for domain, words in _DOMAIN_KEYWORDS.items()
    }
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] > 0 else "general"


def resolve_policy(domain: str | None) -> DomainPolicy:
    return POLICIES.get((domain or "general").strip().lower(), GENERAL_POLICY)
