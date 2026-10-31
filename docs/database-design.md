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

## 4. Index chính

- `courses(user_id)`, `courses(user_id, client_course_id)` unique
- `lessons(course_id)`, `lessons(unit_id, order_index)` unique
- `lesson_attempts(lesson_id, user_id)`, unique `(lesson_id, user_id, client_attempt_id)`
- `generation_jobs(course_id, created_at DESC)`
- `sources(owner_id)`, `sources(visibility, owner_id)`, unique `sources(dedupe_key)`
- `course_sources(course_id)`, `course_sources(source_id)`, unique `(course_id, source_id)`
- `lesson_citations(lesson_id)`, `lesson_citations(source_id)`
- `source_research_runs(course_id, created_at)`, `source_research_runs(user_id)`, unique `(course_id, request_fingerprint)`

## 5. Mở rộng sau (RAG)

- Bảng `sources` (arxiv/web/pdf), `source_chunks` với cột `embedding vector(1536)` + ivfflat index — chỉ thêm ở giai đoạn RAG.
- Bảng `tutor_threads`, `tutor_messages` cho Tutor Engine.
