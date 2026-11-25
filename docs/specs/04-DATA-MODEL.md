# 04 — Data Model, Constraints & Migrations

**Trạng thái (`2026-11-22`):** Đồng bộ trực tiếp với **`backend/app/models/models.py`** (**27 bảng**) và **`backend/alembic/versions/`** (**16 migrations**: `0001_initial` → `0016_p52_exposure`).

## 1. Aggregate relationships (hiện hữu)

```text
users 1--* courses 1--1 course_interviews
                 | 1--* course_proposals (versioned + learnerProfile + skills/prerequisites DAG)
                 | 1--* generation_jobs (outbox + lease + dispatch tracking)
                 | 1--* units 1--* lessons 1--* lesson_attempts
                 |               | 1--* lesson_citations
                 |               ` 1--* lesson_skills *--1 skills 1--* skill_mastery
                 | 1--* course_sources *--1 sources 1--* source_documents 1--* source_chunks 1--* source_chunk_embeddings
                 | 1--* source_research_runs
                 | 1--* tutor_threads 1--* tutor_messages 1--* tutor_tool_calls
                 |                                      ` 1--* tutor_usage_events
                 | 1--* llm_usage_events
                 ` 1--* recommendation_events
users 1--* xp_events
users 1--* review_cards 1--* review_events
```

## 2. Danh mục đầy đủ 27 bảng thực tế

### 2.1 Core & Course Generation (9 bảng — `0001`–`0004`, `0007`)

| Table | Trường nghiệp vụ chính | Constraints / invariants chính |
|---|---|---|
| `users` | `id`, `email`, `password_hash`, `display_name`, `xp`, timestamps | Unique `email`; Argon2id hash |
| `courses` | `id`, `user_id`, `topic`, `status`, `client_course_id`, timestamps | `UNIQUE(user_id, client_course_id)`; `CourseStatus` enum |
| `course_interviews` | `course_id`, `questions` (JSON), `answers` (JSON), `completed_count` | `UNIQUE(course_id)`; 5 câu cố định |
| `course_proposals` | `course_id`, `version`, `payload` (JSON), `approved_at` | `UNIQUE(course_id, version)`; payload chứa `learnerProfile`, `skills[]`, `prerequisites[]` |
| `generation_jobs` | `course_id`, `proposal_version`, `status`, `stage`, `lessons_done`, `lessons_total`, `attempts_count`, `dispatched_at`, `dispatch_attempts`, `lease_expires_at`, `last_error_code`, `error` | Atomic claim; 1 active job/course; pinned `proposal_version` |
| `units` | `course_id`, `order_index`, `title`, `blurb` | `UNIQUE(course_id, order_index)` |
| `lessons` | `course_id`, `unit_id`, `order_index`, `title`, `content` (JSON private), `content_version`, `status`, `grounding` | `UNIQUE(unit_id, order_index)`; private answer keys chỉ lưu tại đây |
| `lesson_attempts` | `lesson_id`, `user_id`, `client_attempt_id`, `content_version`, `score_correct`, `score_total`, `results`, `xp_awarded` | `UNIQUE(lesson_id, user_id, client_attempt_id)` |
| `xp_events` | `user_id`, `lesson_id`, `content_version`, `amount`, `reason` | Cap XP theo `(user, lesson, content_version)` |

### 2.2 LLM Usage & Source Research (2 bảng — `0006`, `0007`)

| Table | Vai trò | Ghi chú |
|---|---|---|
| `llm_usage_events` | Ghi nhận token, latency, model, stage, `cost_estimate_usd` (nullable khi chưa biết giá) theo job/course | Không lưu prompt hay nội dung người dùng |
| `source_research_runs` | Lưu phiên tìm kiếm/xếp hạng nguồn của `source_research` agent (`status`, `sources`, `analysis`, `tool_calls`) | Flag-gated (`SOURCE_RESEARCH_ENABLED=false`) |

### 2.3 AI Tutor (4 bảng — `0008`–`0010`)

| Table | Vai trò | Constraints / invariants |
|---|---|---|
| `tutor_threads` | Thread theo `(user_id, course_id, lesson_id)` | Owner-scoped theo course |
| `tutor_messages` | Messages `user`/`assistant`, `client_message_id`, `context_ref`, `status`, `cancel_requested_at`, `finish_reason`, `citations` | Unique `(user_id, thread_id, client_message_id)` cho user msg; `replaySupported=false` |
| `tutor_usage_events` | Ghi nhận usage 24h theo `(user_id, course_id, message_id)` để kiểm allowance token/lượt | Không lưu text hội thoại |
| `tutor_tool_calls` | Audit metadata cho 3 tool read-only (`name`, `ok`, `duration_ms`, `summary`, `error_code`) | Không lưu nội dung tool trả về |

### 2.4 Sources, Ingestion, Hybrid RAG & OCR (6 bảng — `0005`, `0011`–`0014`)

| Table | Vai trò | Ghi chú |
|---|---|---|
| `sources` | Registry nguồn học (`source_type`, `title`, `canonical_url`, `verification_status`, `visibility`, `owner_id`) | Ownership server-side |
| `course_sources` | Liên kết M-N giữa `courses` và `sources` kèm snapshot `evaluation` | Scope duy nhất cho retrieval theo khóa |
| `lesson_citations` | Provenance trích dẫn của lesson (`source_id`, `chunk_id`, `page_number`, `section_anchor`, `validation_status`) | Chỉ ghi pointer đã kiểm chứng |
| `source_documents` | Tài liệu ingest (`origin`: `upload|web|arxiv`, `origin_url`, `origin_meta`, `storage_key`, `checksum`, `pipeline_version`, `status`, `rights_confirmed_at`, `text_source`, `ocr_pages`, `ocr_engine`, `ocr_version`) | Idempotent theo `(source_id, checksum, pipeline_version)`; `storage_key` private |
| `source_chunks` | Các đoạn văn bản đã tách (`page_number`, `char_start`, `char_end`, `section_anchor`, `text_hash`, `text`, `text_source`, `ocr_confidence`, `ocr_bbox`) | Filter owner/course trong SQL trước khi rank |
| `source_chunk_embeddings` | Vector JSON + spec `(provider, model, dimension, version)` theo chunk | Exact cosine trên Python; không dùng chéo vector khác spec; `pgvector` DEFERRED |

### 2.5 Adaptive Learning & Exposure Logging (6 bảng — `0015`, `0016`)

| Table | Vai trò | Ghi chú |
|---|---|---|
| `skills` | Skill ổn định của course (`skill_key`, `title`, `bloom_level`, `prerequisites` edges) | Backfill/sync từ `course_proposals.payload.skills` |
| `lesson_skills` | Mapping M-N giữa `lessons` và `skills` | Dùng cho mastery & learning-path |
| `skill_mastery` | Snapshot mastery rule-based (`mastery_score`, `method="rule_based"`, `attempts`, `correct`, `total`) | Heuristic có trọng số thời gian, không phải xác suất hiệu chuẩn |
| `review_cards` | Thẻ ôn tập FSRS theo `(user_id, lesson_id)` (`state`, `due_at`, `stability`, `difficulty`, ...) | `stability`/`difficulty` không lộ ra API |
| `review_events` | Lịch sử chấm FSRS (`rating 1..4`, `client_review_id` unique, `reviewed_at`) | Không tự tạo synthetic history |
| `recommendation_events` | Log exposure cho `P5.2b` (`arm`, `propensity=1.0`, `context_hash`, `policy_version`, dedupe theo version) | Ghi chỉ qua HMAC token server-phát (`P52_EXPOSURE_ENABLED=false`) |

## 3. Lịch sử 17 Alembic migrations (BẤT BIẾN — không sửa ngược)

`0001_initial` → `0002_auth_columns` → `0003_p11_quiz_integrity` → `0004_p12_job_reliability` → `0005_p30_source_registry` → `0006_p2sr_source_research` → `0007_p22_eval_cost` → `0008_p30_tutor_core` → `0009_p31_tutor_controls` → `0010_p31_tutor_tools` → `0011_p40_source_ingest` → `0012_p41_rag` → `0013_p42_web_ingest` → `0014_p43_ocr` → `0015_p50_learner_profile` → `0016_p52_exposure` → `0017_p1_course_language`.

## 4. State machines & ID prefixes

- **CourseStatus:** `interview → proposed → approved → generating → ready | failed`.
- **JobStatus:** `queued → running → ready | failed` (và `running → queued` khi retry có giới hạn).
- **SourceDocumentStatus:** `queued → extracting → ready | no_text | failed`.
- **API ID prefixes:** `usr_`, `crs_`, `lsn_`, `src_`, `doc_`, `chk_`, `tth_`, `tmsg_`, ... (lưu UUID v4 trong DB; parser validate nghiêm ngặt ở tầng API).

## 5. Quy tắc migration & rollback

1. **Tuyệt đối không sửa các migration đã áp dụng (`0001_initial` đến `0016_p52_exposure`).**
2. Mọi migration mới (ví dụ cho `P1-LANG`, glossary `terms`, user settings, hoặc tutor actions sau này) phải theo mẫu **expand-only** trước, kiểm tra `upgrade` + `downgrade` trên PostgreSQL rỗng trong CI (`P6.1`).
3. Trước khi chạy migration trên DB có dữ liệu thật: backup trước, không dùng `docker compose down -v`, không `alembic stamp` mù quáng.
4. Ownership luôn kiểm tra ở server qua JOIN DB theo authenticated `user.id`, không tin ID từ client.
