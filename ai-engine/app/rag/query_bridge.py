"""Phase L4 — Cross-Lingual Query Bridge (`VI <-> EN`) & 20-Domain Pedagogical Routing.

Solves cross-lingual retrieval when a Vietnamese learner (`language='vi'`) studies from
an English primary textbook (`sourceLanguages=['en']`):
  1. Uses explicit LLM-provided `englishQuery` when available.
  2. Deterministically expands Vietnamese academic terms across all 20 SopiSkill domains
     into canonical English equivalents for 0-cost offline FTS & Hashing/Vector retrieval.
"""

from __future__ import annotations

import re

# Deterministic VI -> EN academic bridge covering all 20 SopiSkill domains
VI_TO_EN_ACADEMIC_TERMS: tuple[tuple[str, str], ...] = (
    # Computer Science & AI
    ("cây tìm kiếm nhị phân", "binary search tree"),
    ("cấu trúc dữ liệu", "data structures"),
    ("khoa học máy tính", "computer science"),
    ("trí tuệ nhân tạo", "artificial intelligence"),
    ("xử lý ngôn ngữ tự nhiên", "natural language processing"),
    ("thị giác máy tính", "computer vision"),
    ("cơ sở dữ liệu", "databases sql indexing"),
    ("kỹ thuật phần mềm", "software engineering"),
    ("an toàn thông tin", "cybersecurity"),
    ("mạng máy tính", "computer networks"),
    ("hệ điều hành", "operating systems"),
    ("hệ phân tán", "distributed systems"),
    ("lập trình hướng đối tượng", "object-oriented programming"),
    ("lập trình", "programming python"),
    ("thuật toán", "algorithms"),
    ("giải thuật", "algorithms"),
    ("học máy", "machine learning"),
    ("học sâu", "deep learning neural networks"),
    ("đệ quy", "recursion"),
    ("hàm", "functions parameters"),
    ("vòng lặp", "loops iteration"),
    ("biến", "variables types"),
    ("ngăn xếp", "stack"),
    ("hàng đợi", "queue"),
    ("đồ thị", "graph"),
    ("bảng băm", "hash table"),
    ("sắp xếp", "sorting"),
    # Mathematics & Statistics
    ("đại số tuyến tính", "linear algebra matrices vectors"),
    ("xác suất thống kê", "probability statistics"),
    ("phương trình vi phân", "differential equations"),
    ("toán rời rạc", "discrete mathematics"),
    ("giải tích", "calculus"),
    ("đạo hàm", "derivative differentiation"),
    ("tích phân", "integral integration"),
    ("giới hạn", "limits continuity"),
    ("ma trận", "matrix linear transformation"),
    ("xác suất", "probability distributions"),
    ("thống kê", "statistics hypothesis testing"),
    ("tối ưu hóa", "optimization"),
    ("toán học", "mathematics"),
    ("hình học", "geometry"),
    # Physics & Chemistry & Biology
    ("cơ học lượng tử", "quantum mechanics"),
    ("nhiệt động lực học", "thermodynamics"),
    ("điện từ học", "electromagnetism"),
    ("thiên văn học", "astronomy astrophysics"),
    ("quang học", "optics"),
    ("vật lý", "physics mechanics"),
    ("cơ học", "classical mechanics"),
    ("hóa hữu cơ", "organic chemistry"),
    ("hóa vô cơ", "inorganic chemistry"),
    ("hóa lý", "physical chemistry"),
    ("hóa sinh", "biochemistry"),
    ("hóa học", "chemistry"),
    ("sinh học phân tử", "molecular biology"),
    ("khoa học thần kinh", "neuroscience"),
    ("di truyền học", "genetics"),
    ("vi sinh vật", "microbiology"),
    ("giải phẫu", "anatomy physiology"),
    ("sinh lý học", "physiology"),
    ("sinh thái học", "ecology"),
    ("sinh học", "biology"),
    # Earth, Medicine, Engineering, Design
    ("biến đổi khí hậu", "climate change"),
    ("năng lượng tái tạo", "renewable energy"),
    ("khoa học môi trường", "environmental science"),
    ("địa chất", "geology"),
    ("y tế công cộng", "public health"),
    ("dịch tễ học", "epidemiology"),
    ("dược lý", "pharmacology"),
    ("dinh dưỡng", "nutrition"),
    ("y học", "medicine clinical"),
    ("xử lý tín hiệu", "signal processing"),
    ("điều khiển tự động", "control systems"),
    ("kỹ thuật điện", "electrical engineering"),
    ("cơ khí", "mechanical engineering"),
    ("thiết kế giao diện", "ui design user interface"),
    ("trải nghiệm người dùng", "ux design user experience"),
    ("kiến trúc", "architecture"),
    # Economics, Business, Psychology, Humanities, Law, Education
    ("kinh tế vi mô", "microeconomics supply demand"),
    ("kinh tế vĩ mô", "macroeconomics gdp inflation"),
    ("kinh tế lượng", "econometrics"),
    ("kinh tế học", "economics"),
    ("tài chính", "finance financial markets"),
    ("quản trị kinh doanh", "business management"),
    ("kế toán", "accounting"),
    ("tiếp thị", "marketing"),
    ("khởi nghiệp", "entrepreneurship"),
    ("tâm lý học", "psychology cognitive"),
    ("triết học", "philosophy ethics"),
    ("lịch sử", "history"),
    ("xã hội học", "sociology"),
    ("khoa học chính trị", "political science"),
    ("pháp luật", "law legal studies"),
    ("giáo dục", "education pedagogy"),
    ("ngôn ngữ học", "linguistics"),
    ("văn học", "literature"),
    ("viết học thuật", "academic writing composition"),
)

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "computer-science": ("python", "java", "c++", "programming", "algorithm", "data structure", "database", "sql", "machine learning", "deep learning", "computer science", "lập trình", "thuật toán", "cơ sở dữ liệu", "học máy"),
    "mathematics": ("calculus", "linear algebra", "probability", "statistics", "discrete math", "differential", "toán", "giải tích", "đại số", "xác suất", "thống kê"),
    "physics": ("physics", "mechanics", "quantum", "thermodynamics", "electromagnetism", "astronomy", "vật lý", "cơ học", "lượng tử"),
    "chemistry": ("chemistry", "organic", "inorganic", "biochemistry", "molecule", "hóa học", "hóa hữu cơ"),
    "biology": ("biology", "genetics", "cell", "evolution", "microbiology", "ecology", "sinh học", "di truyền"),
    "medicine-health": ("anatomy", "physiology", "medicine", "nursing", "public health", "nutrition", "y học", "giải phẫu", "dinh dưỡng"),
    "economics-finance": ("economics", "microeconomics", "macroeconomics", "finance", "econometrics", "kinh tế", "tài chính"),
    "business-management": ("business", "accounting", "marketing", "management", "entrepreneurship", "kinh doanh", "kế toán", "quản trị"),
    "psychology": ("psychology", "cognitive", "behavioral", "tâm lý"),
    "social-sciences": ("sociology", "political science", "anthropology", "xã hội học", "chính trị"),
    "history": ("history", "civilization", "lịch sử"),
    "philosophy": ("philosophy", "ethics", "logic", "triết học", "đạo đức"),
    "engineering": ("engineering", "robotics", "signal processing", "control systems", "kỹ thuật", "cơ khí"),
    "earth-environment": ("geology", "climate", "environment", "sustainability", "địa chất", "môi trường"),
    "law": ("law", "constitutional", "legal", "luật", "pháp luật"),
    "education": ("education", "pedagogy", "teaching", "curriculum", "giáo dục", "sư phạm"),
    "design-architecture": ("ux", "ui", "architecture", "graphic design", "thiết kế", "kiến trúc"),
    "foreign-languages": ("linguistics", "grammar", "english", "japanese", "ngôn ngữ", "ngoại ngữ"),
    "literature-arts": ("literature", "poetry", "music", "art history", "văn học", "nghệ thuật"),
    "communication-skills": ("writing", "composition", "rhetoric", "communication", "thuyết trình", "viết học thuật"),
}


def has_vietnamese_diacritics(text: str) -> bool:
    return any(ord(ch) > 127 for ch in (text or ""))


def expand_cross_lingual_query(
    query: str,
    *,
    english_query: str | None = None,
    source_languages: list[str] | None = None,
) -> str:
    """Return an enriched retrieval query bridging Vietnamese queries to English open textbooks."""
    base = " ".join((query or "").split()).strip()
    en_explicit = " ".join((english_query or "").split()).strip()

    langs = {str(x).strip().lower()[:2] for x in (source_languages or []) if x}
    sources_are_english = (not langs) or ("en" in langs)

    if en_explicit:
        if sources_are_english and has_vietnamese_diacritics(base):
            return f"{en_explicit} {base}".strip()
        return f"{base} {en_explicit}".strip() if base else en_explicit

    if not base or not sources_are_english:
        return base

    lowered = base.casefold()
    matched_en: list[str] = []
    for vi_term, en_term in VI_TO_EN_ACADEMIC_TERMS:
        if vi_term in lowered:
            for tok in en_term.split():
                if tok not in matched_en:
                    matched_en.append(tok)

    if not matched_en:
        return base
    en_bridge = " ".join(matched_en[:16])
    return f"{en_bridge} {base}".strip()


def infer_domain_slugs(text: str) -> list[str]:
    lowered = (text or "").casefold()
    hits: list[tuple[int, str]] = []
    for slug, kws in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in kws if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", lowered))
        if score > 0:
            hits.append((score, slug))
    hits.sort(key=lambda x: -x[0])
    return [slug for _, slug in hits[:3]]
