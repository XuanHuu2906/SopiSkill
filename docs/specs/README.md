# SopiSkill / AI Learning Platform — Bộ Specification theo module

**Phiên bản:** 0.1 (bản nháp để review)  
**Ngày soạn:** 2026-10-31  
**Đối tượng:** Product owner, reviewer, OpenCode và kỹ sư triển khai trên Windows.  
**Trạng thái của các tài liệu:** DRAFT SPEC; tài liệu **không** khẳng định code trong repository đã được triển khai đúng như mô tả.

## Bắt đầu đọc

1. [00 — Hiện trạng và quy tắc nguồn](00-STATUS-AND-SOURCES.md): hiểu cái gì đã được *báo cáo* là IMPLEMENTED/TESTED.
2. [01 — Product requirements](01-PRODUCT-REQUIREMENTS.md): mục tiêu và phạm vi.
3. [03 — System architecture](03-SYSTEM-ARCHITECTURE.md) + [04 — Data model](04-DATA-MODEL.md) + [05 — API contracts](05-API-CONTRACTS.md).
4. Các domain specs 06–12, UX, chất lượng, thử nghiệm và roadmap.
5. [16 — Handoff OpenCode](16-ROADMAP-AND-OPENCODE.md) để làm phase tiếp theo; [18 — Traceability](18-REQUIREMENTS-TRACEABILITY.md) để nghiệm thu.

## Danh sách file

| File | Vai trò | Tình trạng chức năng tương ứng theo hồ sơ |
|---|---|---|
| `00-STATUS-AND-SOURCES.md` | Độ tin cậy, baseline, xung đột tài liệu | Báo cáo, cần re-audit repo |
| `01-PRODUCT-REQUIREMENTS.md` | PRD, MVP, out-of-scope | Product specification |
| `02-USER-JOURNEYS.md` | Vai trò, user stories, happy/edge paths | Core flow đã báo cáo; bổ sung tương lai |
| `03-SYSTEM-ARCHITECTURE.md` | Components, boundaries, jobs, deployment | Stack hiện hữu theo báo cáo |
| `04-DATA-MODEL.md` | Aggregate, constraint, migrations, ownership | Bảng core đã có; Tutor/RAG là đề xuất |
| `05-API-CONTRACTS.md` | REST API, contracts, error/idempotency | Phân biệt hiện hữu và proposed |
| `06-AUTH-AND-SECURITY.md` | Cookie/CSRF/authorization, abuse/privacy | Core auth báo cáo đã có; hardening tiếp |
| `07-COURSE-INTERVIEW-PROPOSAL.md` | Đúng 5 câu, đề cương, vòng đời | Có baseline; chỉnh sửa đề cương chưa xác nhận |
| `08-GENERATION-AND-LLM.md` | Jobs, provider, DAG, cost | P2.0 đã báo cáo, P2.1+ còn đề xuất |
| `09-LESSON-QUIZ-PROGRESS.md` | Blocks, grading, XP, version | P1.1 đã báo cáo |
| `10-AI-TUTOR-SSE.md` | Threads, streaming, tools, stop | P3.0–P3.1 đề xuất |
| `11-SOURCES-AND-RAG.md` | PDF, retrieval, citation/SSRF | P4 đề xuất |
| `12-ADAPTIVE-LEARNING.md` | Skill mastery, FSRS, BKT | P5 tương lai |
| `13-FRONTEND-UX.md` | Routes, states, accessibility | Core routes báo cáo; Tutor/RAG sau |
| `14-QUALITY-AND-OPERATIONS.md` | NFR, logs, backup, deployment | Gate production đề xuất |
| `15-TEST-PLAN.md` | Test matrix & acceptance criteria | Test mới chưa chạy |
| `16-ROADMAP-AND-OPENCODE.md` | Phase gates, prompt/hand-off | Ưu tiên tiếp theo P2.1 |
| `17-DECISION-LOG.md` | Quyết định và câu hỏi mở | Chỉ ghi đã duyệt nếu có bằng chứng |
| `18-REQUIREMENTS-TRACEABILITY.md` | Mapping requirement → phase → test | Kế hoạch trace |
| `19-PEDAGOGY-AND-EVALUATION.md` | Rubrics, DAG, eval set, guardrails | P2.1/P2.2 đề xuất |
| `20-P41-HYBRID-RAG.md` | Hybrid RAG + citation validation | P4.1 IMPLEMENTED |
| `21-P43-OCR.md` | OCR PDF scan (opt-in) | P4.3 IMPLEMENTED |
| `22-P50-LEARNER-PROFILE.md` | Mastery, FSRS, learning path | P5.0 IMPLEMENTED |
| `23-P51-BKT.md` | BKT research-only | P5.1 RESEARCH |
| `24-P52-ADAPTIVE-READINESS.md` | Exposure logging, OPE readiness | P5.2b IMPLEMENTED (flag off) |
| `25-P61-CI-PIPELINE.md` | CI gates, static/dependency scanning | P6.1 IMPLEMENTED (local); runner NOT TESTED |
| `examples/` | JSON/SSE ví dụ mới | **PROPOSED**, không phải API hiện tại |

## Quy ước bắt buộc

- `FACT`: được hỗ trợ bởi evidence đã cung cấp; `REPORTED IMPLEMENTED/TESTED`: được ghi trong nhật ký dự án nhưng **không được chạy lại trong lần soạn spec**; `PROPOSAL`: contract cần chốt và triển khai; `UNKNOWN`: thiếu chứng cứ.
- Repository/branch/HEAD và OpenAPI thực tế **ưu tiên hơn** bản thiết kế này khi đánh giá code đang chạy. Không được dùng các ví dụ proposed làm lý do phá backward compatibility.
- Không sao chép code, UI, assets, prompts, endpoints hoặc bí mật của PolySkill. Các báo cáo nghiên cứu chỉ là tham khảo hành vi; không suy đoán backend, provider hay thuật toán của họ.
- Tất cả endpoint data phải kiểm tra quyền sở hữu ở server; không tin `courseId`, `lessonId`, `contextRef`, `sourceId` từ client.
- Không đưa secrets ra frontend; không log prompt chứa dữ liệu người dùng; không gọi mock là AI thật; không bịa citation.
- Không chạy migration phá dữ liệu, deploy, dùng provider trả phí hoặc push main khi chưa được phê duyệt.

## Nguồn đầu vào sử dụng

Tài liệu người dùng cung cấp: `02_PROJECT_CONTEXT.md`, `03_ROADMAP_AND_BACKLOG.md`, `architecture.md`, `database-design.md`, `development-progress.md`, `implementation-plan.md`, `llm-provider.md`, `migration-runbook.md`, `SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`, `Bao_cao_PolySkill_Gia_su_AI_Tong_hop_Nguon.docx`.

Hai báo cáo gốc `polyskill-analysis-report.md`, `polyskill-dynamic-analysis.md` được các tài liệu trên **nhắc đến** nhưng không có trong bộ file đính kèm được đối chiếu trực tiếp ở lượt soạn này; không gán cho chúng những kết luận mới.

## Ghi chú sử dụng

Bộ specs dùng để **review → phê duyệt → triển khai**. Hãy đưa cả thư mục `specs/` vào repo sau khi kiểm tra không trùng file đã có. Dùng `16-ROADMAP-AND-OPENCODE.md` để yêu cầu agent audit HEAD và lựa chọn phase chưa hoàn thành; không yêu cầu agent tự động implement toàn bộ cùng lúc.
