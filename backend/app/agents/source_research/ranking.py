"""Source ranking & dedupe (P2.SR) — deterministic, giải thích được.

Hai bất biến:
  1. Ứng viên do adapter MOCK trả về **không bao giờ** được nâng lên
     `metadata_verified`, dù trường metadata trông đầy đủ — vì metadata đó không
     có thật. Nó chỉ là `discovered`.
  2. `total` là điểm xếp hạng nội bộ trong một lần nghiên cứu, không phải xác suất
     "nguồn đúng". Thiếu dữ liệu ⇒ tiêu chí `None` và bị loại khỏi mẫu số, không
     bị tính là 0 điểm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urldefrag, urlparse

from app.agents.source_research.policies import DomainPolicy
from app.agents.source_research.schemas import (
    CandidateScores,
    RankedSourceOut,
    SourceCandidate,
    TopicAnalysis,
)

# Ngưỡng "nguồn còn mới" cho tiêu chí freshness (ngày).
FRESHNESS_HORIZON_DAYS = {
    "programming": 1095,
    "medicine": 1825,
    "general": 1825,
}

# Trường bắt buộc tối thiểu để coi metadata là "đã kiểm tra cấu trúc".
_METADATA_FIELDS = (
    "title",
    "canonicalUrl",
    "publisher",
    "author",
    "publicationDate",
    "language",
    "version",
    "licenseInfo",
)

_WORD_RE = re.compile(r"[\w\-+.]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall((text or "").casefold()) if len(word) >= 3}


def canonical_key(candidate: SourceCandidate) -> str:
    """Khóa chống trùng: URL đã bỏ fragment + chuẩn hoá hoa/thường; nếu không có URL
    thì dùng adapter + candidateId."""
    if candidate.canonicalUrl:
        url, _fragment = urldefrag(candidate.canonicalUrl.strip())
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        path = parsed.path.rstrip("/") or "/"
        query = f"?{parsed.query}" if parsed.query else ""
        return f"url:{host}{path}{query}"
    return f"id:{candidate.adapter}:{candidate.candidateId}"


def dedupe_candidates(candidates: list[SourceCandidate]) -> tuple[list[SourceCandidate], list[str]]:
    """Giữ ứng viên đầu tiên cho mỗi canonical key; trả kèm cảnh báo (không log URL)."""
    seen: set[str] = set()
    kept: list[SourceCandidate] = []
    warnings: list[str] = []
    for candidate in candidates:
        key = canonical_key(candidate)
        if key in seen:
            warnings.append(
                f"Bỏ {len(warnings) + 1} ứng viên trùng canonical URL (không log URL để tránh lộ dữ liệu)."
            )
            continue
        seen.add(key)
        kept.append(candidate)
    return kept, warnings


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _relevance(candidate: SourceCandidate, analysis: TopicAnalysis) -> tuple[float | None, str]:
    topic_tokens = _tokens(analysis.mainTopic)
    for sub in analysis.subTopics:
        topic_tokens |= _tokens(sub)
    if not topic_tokens:
        return None, "Không có từ khoá chủ đề để so khớp."
    haystack = _tokens(
        " ".join(
            filter(
                None,
                [
                    candidate.title,
                    candidate.publisher or "",
                    candidate.sourceType.replace("_", " "),
                ],
            )
        )
    )
    hits = topic_tokens & haystack
    if not hits:
        return 0.2, "Không có từ khoá chủ đề trong metadata (so khớp bề mặt)."
    ratio = len(hits) / len(topic_tokens)
    return round(0.35 + 0.65 * ratio, 4), f"Khớp {len(hits)}/{len(topic_tokens)} từ khoá chủ đề."


def _freshness(candidate: SourceCandidate, domain: str, now: datetime) -> tuple[float | None, str | None]:
    stamp = _parse_date(candidate.publicationDate)
    if stamp is None:
        return None, None
    age_days = max(0, (now - stamp).days)
    horizon = FRESHNESS_HORIZON_DAYS.get(domain, FRESHNESS_HORIZON_DAYS["general"])
    score = max(0.0, min(1.0, 1.0 - age_days / horizon))
    return round(score, 4), f"Cách đây {age_days} ngày (ngưỡng {horizon} ngày cho {domain})."


def _metadata_completeness(candidate: SourceCandidate) -> tuple[float, str]:
    present = [name for name in _METADATA_FIELDS if getattr(candidate, name)]
    ratio = len(present) / len(_METADATA_FIELDS)
    return round(ratio, 4), f"{len(present)}/{len(_METADATA_FIELDS)} trường metadata có dữ liệu."


def metadata_verification_status(candidate: SourceCandidate) -> tuple[str, list[str]]:
    """Kiểm tra **cấu trúc** metadata. Không đọc nội dung, không xác minh factual."""
    reasons: list[str] = []
    if candidate.isMock:
        return "discovered", ["Ứng viên mock: metadata không có thật nên không thể xác minh."]

    missing_required: list[str] = []
    if not candidate.canonicalUrl:
        missing_required.append("URL")
    if not (candidate.publisher or candidate.author):
        missing_required.append("nhà xuất bản/tác giả")
    if not candidate.language:
        missing_required.append("ngôn ngữ")
    if not (candidate.publicationDate or candidate.version):
        missing_required.append("ngày xuất bản/phiên bản")

    if missing_required:
        reasons.append("Thiếu " + ", ".join(missing_required) + " ⇒ chỉ ở mức discovered.")
        return "discovered", reasons

    reasons.append(
        "Metadata qua kiểm tra cấu trúc (URL http(s), có nhà xuất bản, ngôn ngữ, "
        "ngày/phiên bản); KHÔNG đồng nghĩa nội dung đúng."
    )
    return "metadata_verified", reasons


@dataclass
class RankedSource:
    candidate: SourceCandidate
    scores: CandidateScores
    verificationStatus: str
    selectionReason: str
    warnings: list[str] = field(default_factory=list)

    @property
    def relevanceScore(self) -> float:
        return self.scores.relevance or 0.0


def rank_candidates(
    candidates: list[SourceCandidate],
    analysis: TopicAnalysis,
    policy: DomainPolicy,
    *,
    max_sources: int = 8,
    now: datetime | None = None,
) -> tuple[list[RankedSource], list[str]]:
    """Chấm điểm + sắp xếp. Không gọi network, không gọi LLM."""
    now = now or datetime.now(UTC)
    warnings: list[str] = []
    ranked: list[RankedSource] = []

    for candidate in candidates:
        weights = policy.weights
        authority = policy.priority_of(candidate.sourceType)
        relevance, relevance_note = _relevance(candidate, analysis)
        freshness, freshness_note = _freshness(candidate, analysis.domain, now)
        completeness, completeness_note = _metadata_completeness(candidate)

        values: dict[str, float | None] = {
            "authority": authority,
            "relevance": relevance,
            "freshness": freshness,
            "metadataCompleteness": completeness,
        }
        known_weight = sum(weights[key] for key, value in values.items() if value is not None)
        total = (
            sum(weights[key] * value for key, value in values.items() if value is not None)
            / known_weight
            if known_weight
            else 0.0
        )

        notes = [relevance_note, completeness_note]
        if freshness_note:
            notes.append(freshness_note)
        else:
            notes.append("Không có ngày xuất bản/cập nhật ⇒ freshness unknown.")

        status, status_reasons = metadata_verification_status(candidate)
        is_official = candidate.sourceType in policy.officialTypes
        reason = (
            f"Loại nguồn '{candidate.sourceType}'"
            f"{' thuộc nhóm chính thức' if is_official else ' không thuộc nhóm chính thức'}"
            f" của lĩnh vực {policy.label} (điểm ưu tiên loại {authority:.2f}"
            f"/{max(policy.typePriority.values()):.2f})."
        )
        if freshness is not None:
            reason += f" Độ mới: {freshness:.2f}."
        else:
            reason += " Độ mới: chưa xác định (unknown, không tính vào mẫu số)."
        reason += " " + " ".join(status_reasons)
        if candidate.isMock:
            reason += " Đây là dữ liệu MOCK, không phải nguồn thật."

        scores = CandidateScores(
            authority=round(authority, 4),
            relevance=relevance,
            freshness=freshness,
            metadataCompleteness=completeness,
            total=round(min(1.0, max(0.0, total)), 4),
            notes=notes,
        )
        ranked.append(
            RankedSource(
                candidate=candidate,
                scores=scores,
                verificationStatus=status,
                selectionReason=reason,
                warnings=status_reasons if status == "discovered" else [],
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.scores.total,
            -(item.scores.relevance or 0.0),
            item.candidate.title.casefold(),
            item.candidate.candidateId,
        )
    )

    if len(ranked) > max_sources:
        warnings.append(
            f"Chỉ giữ {max_sources} nguồn tốt nhất trong {len(ranked)} ứng viên (giới hạn maxSources)."
        )
    return ranked[:max_sources], warnings


def to_ranked_source_out(
    ranked: RankedSource,
    *,
    adapter: str,
    is_mock: bool,
) -> RankedSourceOut:
    candidate = ranked.candidate
    return RankedSourceOut(
        adapter=candidate.adapter or adapter,
        candidateId=candidate.candidateId,
        sourceId=None,
        title=candidate.title,
        sourceType=candidate.sourceType,
        canonicalUrl=candidate.canonicalUrl,
        publisher=candidate.publisher,
        author=candidate.author,
        publicationDate=candidate.publicationDate,
        language=candidate.language,
        version=candidate.version,
        licenseInfo=candidate.licenseInfo,
        verificationStatus=ranked.verificationStatus,  # type: ignore[arg-type]
        relevanceScore=ranked.relevanceScore,
        scores=ranked.scores,
        selectionReason=ranked.selectionReason,
        isMock=candidate.isMock or is_mock,
        deterministic=candidate.deterministic,
        warnings=ranked.warnings,
    )
