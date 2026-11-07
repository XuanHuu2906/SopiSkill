# Database Design — PostgreSQL

> Áp dụng cho vertical slice Course Generator + Lesson Engine. Migration bằng Alembic.

## 1. Tổng quan

- PostgreSQL 16, schema `public`.
- UUID v4 làm PK (định dạng hiển thị thêm prefix ở tầng API, ví dụ `crs_`, `lsn_`).
- Mọi bảng có `created_at` / `updated_at` (timestamptz, default now()).
- Extension `pgvector` chỉ thêm khi triển khai RAG (giai đoạn 2).

## 2. Sơ đồ ERD (text)

```
users 1───n courses 1───1 course_interviews
                │ 1───1 course_proposals
                │ 1───n generation_jobs
                │ 1───n units 1───n lessons 1───n lesson_attempts
                │                                   │ 1───n attempt_results
                └ 1───n xp_events (qua lessons/users)
```

## 3. Bảng

### users
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| display_name | text | |
| xp | int default 0 | tổng XP |
| streak_days | int default 0 | |
| last_active_date | date nullable | phục vụ streak |
| created_at / updated_at | timestamptz | |

### courses
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `crs_*` |
| user_id | UUID FK users, NOT NULL | ownership |
| topic | text NOT NULL, 1..200 | |
| status | enum: interview, proposed, approved, generating, ready, failed | |
| client_course_id | text | idempotency, unique per user |
| created_at / updated_at | timestamptz | |
| UNIQUE(user_id, client_course_id) | | chống tạo trùng khi retry request |

### course_interviews
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| course_id | UUID FK courses, UNIQUE | 1-1 |
| answers | jsonb | mảng tối đa 5 chuỗi |
| questions | jsonb | 5 câu hỏi (mock provider sinh) |
| completed_count | int default 0 | |
| created_at / updated_at | | |

### course_proposals
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| course_id | UUID FK courses | |
| version | int default 1 | tăng khi regenerate |
| payload | jsonb | schema Proposal: name, objective, units[], outcomes[] |
| approved_at | timestamptz nullable | |
| created_at / updated_at | | |
| UNIQUE(course_id, version) | | |

payload.units: `[{title, blurb, lessonTitles: string[]}]` — 2..6 units, tổng 2..40 lessons.

### generation_jobs
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| course_id | UUID FK courses | |
| status | enum: queued, running, ready, failed | |
| stage | text nullable | `reading_answers` / `background` / `outline` / `lessons` |
| lessons_done | int default 0 | |
| lessons_total | int nullable | |
| error | jsonb nullable | {code, message} |
| attempts_count | int default 1 | |
| llm_calls | int default 0 | P2.2; số lời gọi LLM của job |
| prompt_tokens / completion_tokens | int nullable | P2.2; NULL = chưa có / chưa báo cáo |
| cost_estimate_usd | float nullable | P2.2; **NULL = chưa biết giá model**, không phải 0 |
| created_at / updated_at | | |

Retry tạo job mới với `attempts_count = prev + 1`.

### units
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| course_id | UUID FK courses | |
| order_index | int | |
| title, blurb | text | |
| created_at / updated_at | | |
| UNIQUE(course_id, order_index) | | upsert khi retry |

### lessons
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `lsn_*` |
| unit_id | UUID FK units | |
| course_id | UUID FK courses (denormalized) | |
| order_index | int | |
| title | text | |
| content | jsonb | mảng blocks |
| content_version | int default 1 | versioning |
| status | enum: pending, ready, failed | |
| grounding | enum: source_grounded, general_ai_knowledge | P3.0; default 'general_ai_knowledge' |
| created_at / updated_at | | |
| UNIQUE(unit_id, order_index) | | |

Block types: `teach` (paragraphs), `mc` (question, options, answerIndex), `blank` (sentence, answer), `order` (items đúng thứ tự), `match` (pairs), `short` (question, acceptedAnswers[]).

### llm_usage_events (P2.2)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| job_id | UUID FK generation_jobs nullable | NULL cho lời gọi trong request (interview/proposal) |
| user_id | UUID FK users nullable | owner khi biết; không chứa PII |
| provider, model, kind | text | kind: interview/proposal/lesson/judge/other |
| prompt_tokens / completion_tokens / reasoning_tokens | int nullable | provider trả gì lưu nấy |
| latency_ms | int nullable | đo tại adapter |
| finish_reason | text nullable | stop/length/... |
| cost_estimate_usd | float nullable | NULL = chưa cấu hình giá, không phải miễn phí |
| created_at | timestamptz | index `created_at`, index `job_id` |

Không lưu prompt, câu trả lời người học hay nội dung sinh ra.

### tutor_threads (P3.0 — revision `0008_p30_tutor_core`)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `tth_*` |
| user_id | UUID FK users | owner; truy vấn luôn scoped theo cột này |
| course_id | UUID FK courses | phải khớp course trong path |
| lesson_id | UUID FK lessons | ngữ cảnh mặc định của thread |
| title | text default '' | lấy từ câu hỏi đầu tiên (cắt 120 ký tự) |
| message_count | int default 0 | số lượt hỏi đã chấp nhận (đếm hiển thị; quota thật đếm từ `tutor_messages`) |
| created_at / updated_at | timestamptz | index `(user_id, course_id, updated_at)` |

### tutor_messages (P3.0)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `tmsg_*` |
| thread_id | UUID FK tutor_threads | |
| course_id | UUID FK courses | denormalized để UNIQUE theo course hoạt động |
| position | int NOT NULL default 0 | thứ tự logic (user chẵn, assistant lẻ); **không** dựa timestamp |
| role | enum: user, assistant | |
| status | enum: pending, running, completed, failed, cancelled | `running` còn lại = tiến trình chết, không phải "đã xong" |
| content | text default '' | ghi dần trong stream; final khi status terminal |
| context_ref | jsonb nullable | `{lessonId, lessonTitle, blockIndex, blockType}` do server dựng |
| client_message_id | text nullable | idempotency; NULL cho dữ liệu legacy |
| error_code, finish_reason | text nullable | mã lỗi đã chuẩn hoá / stop/… |
| prompt_tokens, completion_tokens | int nullable | usage nếu provider trả |
| cancel_requested_at | timestamptz nullable | **P3.1** cờ stop do client yêu cầu; NULL = chưa ai dừng |
| created_at / updated_at | timestamptz | index `(thread_id, position)`, index `status` (P3.1) |
| UNIQUE(course_id, client_message_id, role) | | chống double-send ⇒ không gọi provider lần 2 |

> Không lưu system prompt, đáp án quiz hay nội dung nguồn. `context_ref` chỉ chứa
> metadata vị trí; nội dung bài học được đọc lại từ `lessons.content` (public projection).

### tutor_usage_events (P3.1 — revision `0009_p31_tutor_controls`)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users | dùng để cộng allowance 24h |
| course_id / message_id | UUID FK nullable | truy vết lượt gọi về ngữ cảnh |
| provider, model | text | adapter + model thực tế |
| prompt_tokens / completion_tokens | int nullable | NULL = provider không báo, **không** phải 0 |
| latency_ms | int nullable | đo tại adapter |
| finish_reason | text nullable | stop/length/… |
| created_at | timestamptz | index `(user_id, created_at)` |

Metadata-only: **không** có cột prompt/câu trả lời/nội dung sinh ra. Trần token tính bằng
tổng `prompt_tokens + completion_tokens` của 24h gần nhất; nếu provider không báo token,
trần này không chặn được chi phí thật (`tokensKnown=false` trong API usage).

### tutor_tool_calls (P3.1 lát B — revision `0010_p31_tutor_tools`)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| user_id / course_id | UUID FK | scope audit theo owner/course |
| message_id | UUID FK tutor_messages (ON DELETE CASCADE) | audit gắn đúng lượt trả lời |
| name | text | tên tool **đã** nằm trong allowlist hoặc là request bị chặn |
| ok | bool | tool chạy thành công hay bị từ chối/lỗi |
| duration_ms | int nullable | thời gian execute |
| summary | text | mô tả do server dựng (args đã validate + ok/fail), cắt 400 ký tự |
| error_code | text nullable | `TUTOR_TOOL_NOT_ALLOWED` / `TUTOR_TOOL_INVALID_ARGS` / `TUTOR_TOOL_NOT_AVAILABLE` / … |
| created_at | timestamptz | index `(message_id)`, `created_at` |

Metadata-only: **không** có cột nội dung tool trả về, args thô của model hay prompt/câu trả lời.
Index `message_id` để xem toàn bộ tool của một lượt; FK cascade để xóa thread không để lại audit mồ côi.

### lesson_attempts
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| lesson_id | UUID FK lessons | |
| user_id | UUID FK users | |
| client_attempt_id | text | idempotency |
| content_version | int | snapshot version lúc làm |
| score_correct | int | |
| score_total | int | |
| duration_ms | int nullable | |
| results | jsonb | mảng results đã chấm (server-side) |
| created_at | | |
| UNIQUE(lesson_id, user_id, client_attempt_id) | | chống nộp trùng |

### xp_events
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users | |
| lesson_id | UUID FK lessons nullable | |
| amount | int | |
| reason | text | `lesson_completed`, `quiz_score`, ... |
| created_at | | |

### sources (P3.0 — revision `0005_p30_source_registry`)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `src_*` |
| source_type | enum: official_documentation, academic, user_document, webpage | |
| title | text NOT NULL | |
| canonical_url | text nullable | chỉ http(s); **không** suy ra độ tin cậy |
| author, publisher | text nullable | |
| publication_date, source_updated_at, retrieved_at | timestamptz nullable | |
| language, version | text nullable | `version` snapshot vào citation |
| owner_id | UUID FK users nullable | NULL = public |
| visibility | enum: public, private | |
| license_info | text nullable | license hạn chế ⇒ evaluator penalize |
| content_hash | text nullable | móc nối ingestion P4 |
| verification_status | enum (7 giá trị, xem model) | luôn khởi tạo `unverified` |
| dedupe_key | text NOT NULL | sha256(scope, type, url/title, hash) |
| created_at / updated_at | | |
| UNIQUE(dedupe_key) | | chống duplicate |

> Bảng này **không** chứa nội dung tài liệu. Text/chunks/embeddings thuộc P4.

### course_sources
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| course_id | UUID FK courses | |
| source_id | UUID FK sources | |
| evaluation | jsonb nullable | snapshot đánh giá tại thời điểm liên kết |
| created_at | | |
| UNIQUE(course_id, source_id) | | liên kết idempotent |

### lesson_citations
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `cit_*` |
| lesson_id | UUID FK lessons | |
| source_id | UUID FK sources | FK bảo đảm không trỏ nguồn không tồn tại |
| source_version | text nullable | snapshot; lệch bản hiện tại ⇒ `source_changed` |
| chunk_id, section_anchor | text nullable | P4 mới xác minh được |
| page_number | int nullable | |
| evidence_text | text nullable | chỉ chứa text **thật** từ nguồn (P4) |
| validation_status | enum (6 giá trị) | P3.0 chỉ tạo unverified/unavailable/source_changed/rejected |
| created_at | | |

### source_research_runs (P2.SR — revision `0006_p2sr_source_research`)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `rr_*` |
| course_id | UUID FK courses | |
| user_id | UUID FK users | owner tại thời điểm chạy; truy vấn scoped |
| status | enum: running, completed, insufficient_evidence, failed | |
| topic, domain | text | snapshot chủ đề/domain lúc chạy |
| adapter | text | mock/curated/... (ghi lại nguồn gốc kết quả) |
| is_mock | bool | true ⇒ kết quả KHÔNG có thật, không được link vào course |
| request_fingerprint | text | sha256(courseId, topic, level, goals, language, maxSources, adapter) |
| analysis | jsonb nullable | TopicAnalysis snapshot |
| sources | jsonb (default `[]`) | danh sách RankedSourceOut — **không** có `sourceId` registry |
| warnings | jsonb (default `[]`) | |
| error | jsonb nullable | `{code, message, retryable}` khi failed |
| insufficient_evidence | bool | |
| tool_calls | int | số tool call agent đã dùng (bounded) |
| created_at, updated_at | | |
| UNIQUE(course_id, request_fingerprint) | | idempotency: retry không nhân bản run |

### source_documents (P4.0 — revision `0011_p40_source_ingest`)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | hiển thị `doc_*` |
| source_id | UUID FK sources (ON DELETE CASCADE) | tài liệu thuộc một nguồn |
| content_hash | text NOT NULL | sha256 của file gốc |
| mime | text | luôn `application/pdf` sau khi xác minh magic |
| byte_size / page_count | int | page_count do server đếm, không tin client |
| pipeline_version | text | đổi giá trị ⇒ re-ingest thành document mới |
| status | enum: queued, extracting, ready, no_text, failed | `no_text` = PDF scan, KHÔNG phải OCR |
| original_filename | text nullable | basename đã làm sạch để hiển thị (không phải path) |
| storage_key | text NOT NULL | object key **ngẫu nhiên** trong private storage |
| attempts_count / max_attempts | int | retry bounded |
| lease_expires_at / heartbeat_at / dispatched_at / dispatch_attempts | | outbox + lease (giống generation job) |
| error_code / error | text / jsonb | message ngắn, KHÔNG chứa text tài liệu |
| ingested_at | timestamptz | thời điểm trích xong |
| created_at / updated_at | | |
| UNIQUE(source_id, content_hash, pipeline_version) | | retry cùng bytes không nhân bản |

> Bảng này **không** chứa text. Không có cột `embedding` (P4.1).

### source_chunks (P4.0)
| cột | kiểu | ghi chú |
|---|---|---|
| id | UUID PK | |
| document_id | UUID FK source_documents (CASCADE) | |
| source_id | UUID FK sources (CASCADE) | denormalized để filter owner/source ở query |
| chunk_index | int | unique trong document |
| page_number | int | 1-based, theo trang PDF |
| char_start / char_end | int | offset trong text **của trang**, không phải byte PDF |
| section_anchor | text nullable | heading gần nhất (dòng ngắn không kết thúc bằng dấu câu) |
| text | text | nội dung **untrusted**; chỉ dùng làm `evidence_text` khi có retrieval (P4.1) |
| text_hash | text | sha256 của text đã chuẩn hoá whitespace |
| created_at | | |
| UNIQUE(document_id, chunk_index) | | không overlap, không trùng |

## 4. Index chính

- `courses(user_id)`, `courses(user_id, client_course_id)` unique
- `lessons(course_id)`, `lessons(unit_id, order_index)` unique
- `lesson_attempts(lesson_id, user_id)`, unique `(lesson_id, user_id, client_attempt_id)`
- `generation_jobs(course_id, created_at DESC)`
- `sources(owner_id)`, `sources(visibility, owner_id)`, unique `sources(dedupe_key)`
- `course_sources(course_id)`, `course_sources(source_id)`, unique `(course_id, source_id)`
- `lesson_citations(lesson_id)`, `lesson_citations(source_id)`
- `source_research_runs(course_id, created_at)`, `source_research_runs(user_id)`, unique `(course_id, request_fingerprint)`
- `source_documents(source_id)`, `source_documents(status, created_at)`, unique `(source_id, content_hash, pipeline_version)`
- `source_chunks(document_id)`, `source_chunks(source_id)`, `source_chunks(source_id, page_number)`
- `skills(course_id)`, unique `(course_id, key)` — P5.0
- `lesson_skills(skill_id)`, PK `(lesson_id, skill_id)` — P5.0
- `skill_mastery(skill_id)`, PK `(user_id, skill_id)` — P5.0
- `review_cards(user_id)`, `review_cards(user_id, due_at)`, unique `(user_id, lesson_id)` — P5.0
- `review_events(card_id)`, `review_events(card_id, reviewed_at)`, `review_events(user_id, reviewed_at)`, unique `(card_id, client_review_id)` — P5.0

### source_chunk_embeddings (P4.1 — revision `0012_p41_rag`)

- `chunk_id`, `source_id` (denormalized để filter quyền ngay tại SQL), `provider`, `model`,
  `dimension`, `version`, `text_hash` (snapshot của chunk lúc embed), `vector` (JSON array).
- UNIQUE `(chunk_id, provider, model, dimension, version)` ⇒ một vector/spec/chunk; đổi
  model **không** ghi đè vector cũ, và không thể trộn hai không gian vector.
- `text_hash` khác `source_chunks.text_hash` ⇒ vector stale, bị loại khỏi xếp hạng.
- Index `(provider, model, dimension, version)` (chọn đúng spec), `(chunk_id)`, `(source_id)`.
- Index `source_chunks(text_hash)` (phát hiện chunk đổi nội dung) và GIN
  `to_tsvector('simple', text)` chỉ trên PostgreSQL cho lexical retrieval.

`tutor_messages.citations` (JSONB, nullable) lưu citation **đã verify**; NULL = không có RAG
hoặc không đủ căn cứ.

### P5.0 — Learner profile, mastery & FSRS (revision `0015_p50_learner_profile`)

| Bảng | Vai trò | Ghi chú trung thực |
|---|---|---|
| `skills` | Skill ổn định trong **một** course, backfill từ `CurriculumSkill` của proposal | `key` = `CurriculumSkill.id`; `UNIQUE(course_id, key)`; **upsert**, không delete+insert (CASCADE sẽ xoá mastery) |
| `lesson_skills` | Liên kết lesson ↔ skill | Map theo **vị trí** `(unit.order_index, lesson.order_index)`, không theo title (provider ghi đè `lesson.title`) |
| `skill_mastery` | Snapshot mastery `(user, skill)` | `mastery_score` là **heuristic** accuracy có trọng số thời gian (half-life 30 ngày) — **không phải** xác suất đã hiệu chuẩn |
| `review_cards` | Snapshot FSRS hiện tại `(user, lesson)` | `scheduler_version` pin thuật toán; `state/step/stability/difficulty` là dữ liệu nội bộ, **không** trả ra API người học |
| `review_events` | Audit append-only mỗi lần review | `client_review_id` unique theo card ⇒ retry không nhân bản; `elapsed_days`/`scheduled_days` do server tự tính (thư viện `fsrs` không trả) |

Quyết định đã chốt: card tạo ngay ở **attempt đầu tiên** (kể cả <80%) để ôn bài yếu là luồng
thật; `learning_steps=()` để lịch theo ngày (Again 1d / Hard 1d / Good 2d / Easy 8d, đo với
`py-fsrs-6.3.2`, `enable_fuzzing=False`); `contentVersion` đổi **không** reset mastery — mastery
chỉ tính attempt đúng version hiện hành nên tự rơi về 0 cho tới khi học lại. Chi tiết:
`docs/specs/22-P50-LEARNER-PROFILE.md`.

## 5. Mở rộng sau (RAG)

- P4.0 **đã có** `source_documents` + `source_chunks` (text/provenance, không embedding).
- P4.1 **đã có** `source_chunk_embeddings` lưu vector dạng **JSON** (không pgvector):
  exact cosine có trần `RAG_CANDIDATE_LIMIT`. Benchmark (`evals/rag_benchmark.py`) cho thấy
  p95 84 ms ở 500 chunk và 368 ms ở 2000 chunk ⇒ **cần pgvector/ANN khi corpus vượt ~700 chunk**.
  Khi chuyển: thêm cột `vector(N)` với dimension của model đã chốt, tạo HNSW **chỉ sau benchmark**,
  backfill song song giữ nguyên bảng JSON để rollback. Không hardcode `1536`.
- P4.2 **đã có**: `source_documents.origin` (`upload|web|arxiv`), `origin_url` (URL thật đã
  fetch; NULL với PDF upload), `origin_meta` (JSONB metadata arXiv/HTTP — không chứa nội dung),
  `rights_confirmed_at` (audit xác nhận quyền sử dụng), index `(source_id, origin_url)`.
  Nội dung web được lưu trong private storage dưới dạng blob JSON `{kind:"web_text", text,
  sections, finalUrl}`; arXiv lưu PDF bytes. Worker chunk theo `origin` rồi dùng chung
  `source_chunks`/embedding P4.0–P4.1.
- P4.3: OCR cho PDF scan; khi đó `source_chunks` cần `origin`/bbox nhưng phải đánh dấu rõ khác text native.
