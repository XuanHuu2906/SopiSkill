"""Source Research Agent (P2.SR) — nghiên cứu nguồn độc lập cho Course Generator.

Agent này KHÔNG sinh nội dung khóa học và KHÔNG có quyền ghi DB trực tiếp. Nó chỉ:
  topic analysis → discovery → metadata verification → evaluation → ranking →
  đề xuất danh sách nguồn kèm lý do, rồi giao kết quả cho service layer lưu lại.

Giới hạn trung thực (đọc kỹ trước khi dùng):
  - Adapter mặc định là `mock`/`curated`: **không** gọi internet trong phase này.
  - `metadata_verified` chỉ nghĩa là metadata đã qua kiểm tra **cấu trúc xác định**
    (đủ trường, URL http(s), ngày hợp lệ). Nó KHÔNG có nghĩa nội dung đúng.
  - Agent KHÔNG có tool đọc nội dung nguồn ⇒ không bao giờ tự đặt
    `content_available`/`evidence_verified`, không sinh citation, DOI hay tác giả.
"""

from app.agents.source_research.agent import SourceResearchAgent
from app.agents.source_research.policies import (
    DomainPolicy,
    classify_domain,
    resolve_policy,
)
from app.agents.source_research.ranking import (
    CandidateScores,
    RankedSource,
    dedupe_candidates,
    rank_candidates,
)
from app.agents.source_research.schemas import (
    ResearchError,
    ResearchRequest,
    ResearchResult,
    SourceCandidate,
    TopicAnalysis,
)
from app.agents.source_research.topic import analyze_topic
from app.agents.source_research.tools import (
    ResearchToolbox,
    ToolBudgetExceeded,
    ToolValidationError,
    build_toolbox,
)

__all__ = [
    "CandidateScores",
    "DomainPolicy",
    "RankedSource",
    "ResearchError",
    "ResearchRequest",
    "ResearchResult",
    "ResearchToolbox",
    "SourceCandidate",
    "SourceResearchAgent",
    "ToolBudgetExceeded",
    "ToolValidationError",
    "TopicAnalysis",
    "analyze_topic",
    "build_toolbox",
    "classify_domain",
    "dedupe_candidates",
    "rank_candidates",
    "resolve_policy",
]
