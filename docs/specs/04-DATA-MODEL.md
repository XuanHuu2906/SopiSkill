# 04 — Data Model, Constraints & Migrations

**Trạng thái:** Core tables là mô tả theo `database-design.md` + progress; Tutor/RAG/P5 là **PROPOSAL**. Tên cột cuối cùng cần đối chiếu ORM/migrations tại HEAD.

## 1. Aggregate relationships

```text
users 1--* courses 1--1 course_interviews
                 | 1--* course_proposals (versioned)
                 | 1--* generation_jobs
                 | 1--* units 1--* lessons 1--* lesson_attempts
users 1--* xp_events

P3 proposed: users/courses 1--* tutor_threads 1--* tutor_messages
P4 proposed: users 1--* sources 1--* source_pages/source_chunks
P5 proposed: users 1--* skill_mastery, review_events
```

## 2. Core tables (reported)

| Table | Các trường nghiệp vụ quan trọng | DB constraint/invariant |
|---|---|---|
| `users` | id, email/password_hash (auth), xp, timestamps | unique email; password Argon2id |
| `courses` | id, user_id, topic, status, client_course_id, timestamps | `UNIQUE(user_id, client_course_id)`; topic 1..200 |
| `course_interviews` | course_id, questions jsonb, answers jsonb, completed_count | `UNIQUE(course_id)`; tối đa 5 answers |
| `course_proposals` | course_id, version, payload jsonb, approved_at | `UNIQUE(course_id, version)` |
| `generation_jobs` | course_id, status, stage, lesson counts, error, attempts, dispatched_at, lease fields | claim/idempotency theo job ID; một active job/course |
| `units` | course_id, order_index, title, blurb | `UNIQUE(course_id, order_index)` |
| `lessons` | course_id, unit_id, order_index, title, content jsonb, content_version, status | `UNIQUE(unit_id, order_index)` |
| `lesson_attempts` | lesson_id, user_id, client_attempt_id, content_version, score, results, xp_awarded | `UNIQUE(lesson_id,user_id,client_attempt_id)` |
| `xp_events` | user_id, lesson_id, content_version, amount, reason | XP award invariant per user/lesson/version |

**State**: course `interview → proposed → approved → generating → ready/failed`; generation job `queued → running → ready/failed`, `running → queued` cho retry tạm thời. Chỉ service/worker thay đổi status.

**UUID prefix** (`crs_*`, `lsn_*`) là ID hiển thị qua API; storage UUID v4. Parser phải validate, không chấp nhận SQL injection/unsafe coercion.

## 3. Proposed P2.1 additions — curriculum graph

- `learner_profile_snapshot`: `course_id`, `interview_version` hoặc fingerprint, `profile_schema_version`, `payload`, `created_at`; chỉ chứa dữ liệu học tập tự khai, tránh thuộc tính nhạy cảm suy đoán.
- `curriculum_graph` hoặc field versioned `course_proposals.payload.curriculumGraph`: `nodes[{skillId,label,bloomLevel}]`, `edges[{prerequisiteSkillId,skillId}]`, mapping lesson → objectives. **Một nguồn sự thật**, không nhân bản vô mục đích.
- Freeze/pin `proposal_version` trên generation job. Migration expand-only; khi chưa có graph, legacy proposal vẫn xem/học được.
- Chọn normalize DB hay JSONB sau audit query pattern; có validation DAG không chu trình ở service, không chỉ ở UI.

## 4. Proposed P3 — Tutor data

| Entity | Trường/constraint bắt buộc |
|---|---|
| `tutor_threads` | id, user_id, course_id, created_at, updated_at, status; course must belong to user |
| `tutor_messages` | id, thread_id, user_id, role (user/assistant/tool), client_message_id nullable, context_lesson_id, context_block_index, status, content, provider metadata redacted, timestamps |
| `tutor_tool_calls` (optional normalized) | message_id, name, validated args safe summary, outcome, duration_ms; no secrets/raw source content |
| `tutor_usage` | user_id, time window, reserved/consumed units, request_id, unique idempotency; transactionally enforced |

Unique `(user_id, thread_id, client_message_id)` cho user message; assistant message có link `responds_to_message_id`, unique nếu mỗi request có tối đa một assistant answer. Nếu cần replay từng SSE event, tạo event log riêng trước khi tuyên bố resume hỗ trợ.

## 5. Proposed P4 — sources and citations

- `sources`: id, owner_id, course_id nullable, type (`pdf`/web/arxiv sau), original_name_safe, mime, bytes, checksum, storage_key_private, status, pipeline_version, timestamps.
- `source_pages`: source_id, page_number (1-based), extraction_status, text_hash, page metadata.
- `source_chunks`: id, source_id, page_start, page_end, offsets/anchor, text_hash, text, pipeline_version, embedding_model, embedding_dim, embedding, created_at.
- `source_citations` có thể là record tham chiếu `sourceId/chunkId/page/offset` trên câu trả lời, chỉ ghi nếu xác minh IDs tồn tại và source thuộc user.
- Unique per source/version/chunk ordinal; ingest job idempotent theo `(source_id, checksum, pipeline_version)`.
- **Không** cố định `vector(1536)` khi model/dimension chưa được duyệt; migration pgvector đi sau benchmark và quyết định embed.

## 6. Proposed P5 — learning profile

- `skills` và `lesson_skills` với stable skill ID, prerequisite edges versioned.
- `skill_mastery` lưu baseline rules và metadata version; không gọi số heuristics là calibrated ML probability.
- `review_events` lưu lesson/skill, user, rating, reviewed_at, scheduler version, next_due_at cho FSRS khi bật.
- Không backfill synthetic histories để tạo ảo giác dữ liệu học.

## 7. Migration and rollback rules

1. **Không sửa migration `0001_initial`, `0002_auth_columns`, `0003_p11_quiz_integrity`, `0004_p12_job_reliability` đã báo áp dụng.**
2. Migration mới: expand → backfill (nếu có) → switch reads/writes → contract sau; indexes/unique được kiểm tra trên PostgreSQL test DB.
3. Trước migration rủi ro: backup và kiểm tra phục hồi trên DB tạm; không xóa volume, không `stamp` mù quáng.
4. Mọi migration cần `upgrade`, đánh giá `downgrade` thực dụng (nếu phá dữ liệu, rollback bằng restore), schema inspection và negative tests.
5. Dữ liệu chủ sở hữu phải kiểm tra server-side bằng join/query course/lesson/source, không dựa duy nhất FK `user_id` do client cấp.
