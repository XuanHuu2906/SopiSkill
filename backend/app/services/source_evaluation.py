"""Source Quality Evaluation (P3.0) — deterministic, metadata-only.

Đây là evaluator **MVP**: chỉ nhìn metadata có cấu trúc + allowlist cấu hình.
Nó KHÔNG đọc nội dung, KHÔNG đánh giá độ đúng factual, KHÔNG thay thế review của
con người. Vì vậy:

  - Tiêu chí thiếu dữ liệu ⇒ `status=unknown`, `score=None`, và **bị loại khỏi
    mẫu số** thay vì được cho điểm cao/0 điểm ngầm.
  - `weightedScore` chỉ tính trên trọng số có dữ liệu; nếu độ phủ dữ liệu dưới
    ngưỡng ⇒ verdict `insufficient_metadata` và `weightedScore=None`.
  - Kết quả chỉ là **đề xuất** (`suggestedVerificationStatus`); không tự ghi
    `verified` vào DB.
  - License thiếu hoặc cấm lưu trữ là tín hiệu `penalized` độc lập (không cộng
    điểm), vì không có quyền lưu trữ thì không nên sinh nội dung từ nguồn.

Công thức (đọc kỹ trước khi tin):
  score(criterion) ∈ [0, 1]; unknown ⇒ None.
  weightedScore = Σ(score_i × w_i) / Σ(w_i)  với i chỉ gồm tiêu chí có score.
  coverage      = Σ(w_i có score) / Σ(w_i toàn bộ)              ∈ [0, 1]
  verdict       = insufficient_metadata nếu coverage < MIN_COVERAGE
                  ngược lại theo ngưỡng weightedScore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models import Source, SourceType, SourceVerificationStatus

MIN_COVERAGE = 0.5

# Trọng số tiêu chí. Tổng = 1.0 để đọc dễ; công thức chuẩn hoá theo trọng số có
# dữ liệu nên tổng không bắt buộc phải bằng 1.
WEIGHTS: dict[str, float] = {
    "authority": 0.25,
    "relevance": 0.20,
    "freshness": 0.15,
    "evidence": 0.20,
    "consistency": 0.10,
    "licensing": 0.10,
}

LABELS: dict[str, str] = {
    "authority": "Authority — tác giả/tổ chức xuất bản",
    "relevance": "Relevance — mức phù hợp chủ đề",
    "freshness": "Freshness — thời điểm xuất bản/cập nhật",
    "evidence": "Evidence — khả năng kiểm chứng nội dung",
    "consistency": "Consistency — mâu thuẫn với nguồn khác",
    "licensing": "Licensing — quyền sử dụng/lưu trữ",
}

# Allowlist publisher/tên miền do người vận hành cấu hình. Rỗng = chưa cấu hình,
# mọi authority là unknown (KHÔNG mặc định "đáng tin").
DEFAULT_TRUSTED_PUBLISHERS: tuple[str, ...] = ()

FRESHNESS_MAX_AGE_DAYS = {
    SourceType.official_documentation: 730,
    SourceType.academic: 1825,
    SourceType.webpage: 365,
    SourceType.user_document: 3650,
}


@dataclass
class Criterion:
    key: str
    status: str  # strong | moderate | weak | unknown | penalized
    score: float | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": LABELS.get(self.key, self.key),
            "status": self.status,
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass
class Evaluation:
    criteria: list[Criterion]
    known_weight: float
    total_weight: float
    weighted_score: float | None
    verdict: str
    suggested_status: SourceVerificationStatus
    limitations: list[str]

    def to_dict(self) -> dict:
        return {
            "criteria": [c.to_dict() for c in self.criteria],
            "knownWeight": round(self.known_weight, 4),
            "totalWeight": round(self.total_weight, 4),
            "weightedScore": None if self.weighted_score is None else round(self.weighted_score, 4),
            "verdict": self.verdict,
            "suggestedVerificationStatus": self.suggested_status.value,
            "limitations": list(self.limitations),
            "evaluator": {
                "kind": "deterministic_metadata",
                "version": "p3.0-v1",
                "minCoverage": MIN_COVERAGE,
                "weights": dict(WEIGHTS),
            },
        }


def _authority(source: Source, trusted: tuple[str, ...]) -> Criterion:
    publisher = (source.publisher or "").strip().casefold()
    author = (source.author or "").strip()
    allowlist = {entry.strip().casefold() for entry in trusted if entry.strip()}

    if not publisher and not author:
        return Criterion("authority", "unknown", None, ["Không có tác giả hay nhà xuất bản."])

    trust_source = ""
    if publisher and allowlist:
        if any(entry in publisher for entry in allowlist):
            return Criterion(
                "authority", "strong", 0.9, [f"Nhà xuất bản nằm trong allowlist cấu hình: {source.publisher}."]
            )
        trust_source = "Nhà xuất bản không nằm trong allowlist."

    # Không có allowlist, hoặc không khớp: dựa vào loại nguồn + tác giả có tên.
    base = {
        SourceType.official_documentation: 0.7,
        SourceType.academic: 0.65,
        SourceType.user_document: 0.4,
        SourceType.webpage: 0.35,
    }[source.source_type]
    reasons = [f"Loại nguồn '{source.source_type.value}' (không phải bằng chứng độ tin cậy)."]
    if author:
        base += 0.05
        reasons.append(f"Có tác giả được ghi tên: {author[:80]}.")
    if publisher:
        reasons.append(f"Nhà xuất bản: {source.publisher}.")
    if trust_source:
        reasons.append(trust_source)
    reasons.append("Chưa cấu hình allowlist ⇒ không thể xác nhận uy tín tổ chức.")
    status = "moderate" if base >= 0.5 else "weak"
    return Criterion("authority", status, round(min(base, 0.75), 4), reasons)


def _relevance(source: Source, topics: list[str]) -> Criterion:
    """Keyword overlap giữa title/topic — thô, chỉ để loại nguồn lạc đề rõ ràng."""
    if not topics:
        return Criterion("relevance", "unknown", None, ["Chưa có chủ đề khóa học để so khớp."])
    haystack = " ".join(
        filter(None, [source.title or "", source.publisher or "", source.language or ""])
    ).casefold()
    hits = 0
    for topic in topics:
        words = [w for w in topic.casefold().split() if len(w) >= 3]
        if words and any(word in haystack for word in words):
            hits += 1
    if hits == 0:
        return Criterion(
            "relevance", "weak", 0.2, ["Không tìm thấy từ khoá chủ đề trong metadata nguồn (so khớp thô)."]
        )
    ratio = hits / len(topics)
    return Criterion(
        "relevance",
        "moderate" if ratio >= 0.5 else "weak",
        round(0.4 + 0.5 * ratio, 4),
        [f"{hits}/{len(topics)} chủ đề khớp keyword trong metadata (chỉ là so khớp bề mặt)."],
    )


def _freshness(source: Source, now: datetime | None = None) -> Criterion:
    now = now or datetime.now(UTC)
    stamp = source.source_updated_at or source.publication_date
    if stamp is None:
        return Criterion("freshness", "unknown", None, ["Không có ngày xuất bản/cập nhật."])
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    age_days = max(0, (now - stamp).days)
    limit = FRESHNESS_MAX_AGE_DAYS[source.source_type]
    ratio = age_days / limit if limit else 1.0
    score = round(max(0.0, min(1.0, 1.0 - ratio)), 4)
    if ratio <= 0.5:
        status = "strong"
    elif ratio <= 1.0:
        status = "moderate"
    else:
        status = "weak"
    return Criterion(
        "freshness",
        status,
        score,
        [f"Cách đây {age_days} ngày; ngưỡng tham chiếu {limit} ngày cho loại '{source.source_type.value}'."],
    )


def _evidence(source: Source, has_content: bool) -> Criterion:
    reasons: list[str] = []
    score = 0.0
    if source.canonical_url:
        score += 0.25
        reasons.append("Có URL để đối chiếu thủ công.")
    if source.content_hash:
        score += 0.35
        reasons.append("Có content hash (phát hiện thay đổi nguồn).")
    if has_content:
        score += 0.3
        reasons.append("Có nội dung đã ingest để kiểm tra locator.")
    if source.version:
        score += 0.1
        reasons.append("Có version.")
    if score == 0:
        return Criterion("evidence", "unknown", None, ["Không có URL/hash/nội dung để kiểm chứng."])
    if score < 0.4:
        status = "weak"
    elif score < 0.7:
        status = "moderate"
    else:
        status = "strong"
    reasons.append("Kiểm chứng locator KHÔNG đồng nghĩa nội dung hỗ trợ claim.")
    return Criterion("evidence", status, round(min(score, 1.0), 4), reasons)


def _consistency(has_conflicts: bool | None) -> Criterion:
    if has_conflicts is None:
        return Criterion(
            "consistency", "unknown", None, ["Chưa so sánh với nguồn khác — không suy đoán."]
        )
    if has_conflicts:
        return Criterion("consistency", "penalized", 0.0, ["Có xung đột đã biết với nguồn khác."])
    return Criterion("consistency", "strong", 0.8, ["Không phát hiện xung đột với các nguồn đã liên kết."])


def _licensing(source: Source) -> Criterion:
    info = (source.license_info or "").strip()
    if not info:
        return Criterion(
            "licensing",
            "unknown",
            None,
            ["Chưa khai báo license ⇒ không kết luận được quyền lưu trữ/sinh nội dung."],
        )
    lowered = info.casefold()
    if any(word in lowered for word in ("all rights reserved", "proprietary", "không được phép", "no redistribution")):
        return Criterion(
            "licensing", "penalized", 0.0, [f"License hạn chế quyền sử dụng/lưu trữ: {info[:120]}."]
        )
    return Criterion(
        "licensing",
        "moderate",
        0.6,
        [f"License được khai báo: {info[:120]} (chưa xác minh với văn bản license gốc)."],
    )


def evaluate_source(
    source: Source,
    *,
    topics: list[str] | None = None,
    has_content: bool = False,
    has_conflicts: bool | None = None,
    trusted_publishers: tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> Evaluation:
    trusted = DEFAULT_TRUSTED_PUBLISHERS if trusted_publishers is None else trusted_publishers
    criteria = [
        _authority(source, trusted),
        _relevance(source, [t for t in (topics or []) if t and t.strip()]),
        _freshness(source, now),
        _evidence(source, has_content),
        _consistency(has_conflicts),
        _licensing(source),
    ]

    total_weight = sum(WEIGHTS[c.key] for c in criteria)
    known = [c for c in criteria if c.score is not None]
    known_weight = sum(WEIGHTS[c.key] for c in known)
    coverage = known_weight / total_weight if total_weight else 0.0

    if not known or coverage < MIN_COVERAGE:
        return Evaluation(
            criteria=criteria,
            known_weight=known_weight,
            total_weight=total_weight,
            weighted_score=None,
            verdict="insufficient_metadata",
            suggested_status=SourceVerificationStatus.pending_review,
            limitations=[
                "Không đủ metadata để chấm điểm tổng hợp; cần review thủ công.",
                "Evaluator chỉ dùng metadata, không đọc nội dung và không xác minh tính đúng.",
            ],
        )

    weighted = sum(WEIGHTS[c.key] * c.score for c in known) / known_weight
    if weighted >= 0.7:
        verdict = "strong"
        suggested = SourceVerificationStatus.metadata_verified
    elif weighted >= 0.45:
        verdict = "moderate"
        suggested = SourceVerificationStatus.pending_review
    else:
        verdict = "weak"
        suggested = SourceVerificationStatus.pending_review

    # License bị hạn chế ⇒ không bao giờ đề xuất metadata_verified.
    if any(c.key == "licensing" and c.status == "penalized" for c in criteria):
        suggested = SourceVerificationStatus.pending_review
        verdict = "weak"

    return Evaluation(
        criteria=criteria,
        known_weight=known_weight,
        total_weight=total_weight,
        weighted_score=weighted,
        verdict=verdict,
        suggested_status=suggested,
        limitations=[
            "Điểm phản ánh metadata, KHÔNG phải độ đúng nội dung hay độ tin cậy tuyệt đối.",
            "Tiêu chí thiếu dữ liệu được đánh dấu unknown và loại khỏi mẫu số.",
            "Relevance chỉ so khớp keyword bề mặt; consistency mặc định unknown.",
        ],
    )
