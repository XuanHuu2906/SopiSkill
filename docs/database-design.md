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

## 4. Index chính

- `courses(user_id)`, `courses(user_id, client_course_id)` unique
- `lessons(course_id)`, `lessons(unit_id, order_index)` unique
- `lesson_attempts(lesson_id, user_id)`, unique `(lesson_id, user_id, client_attempt_id)`
- `generation_jobs(course_id, created_at DESC)`

## 5. Mở rộng sau (RAG)

- Bảng `sources` (arxiv/web/pdf), `source_chunks` với cột `embedding vector(1536)` + ivfflat index — chỉ thêm ở giai đoạn RAG.
- Bảng `tutor_threads`, `tutor_messages` cho Tutor Engine.
