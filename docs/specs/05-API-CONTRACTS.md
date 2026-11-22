# 05 — HTTP API & Contract Policy

**Trạng thái (`2026-11-22`):** Danh mục **45 endpoints** ở mục 1 được đối chiếu trực tiếp từ `backend/app/main.py` và `backend/app/api/v1/{auth,routes,tutor,sources,research,learner}.py`. Các mục gắn nhãn `PROPOSAL` (mục 8) chưa có code và không phá backward compatibility hiện hành.

## 1. Danh mục đầy đủ 45 endpoints thực tế

### 1.1 Health & Auth (5 endpoints — `main.py`, `api/v1/auth.py`)

| Method & path | Status | Auth / CSRF / Ghi chú |
|---|---|---|
| `GET /health` | `200` | Public; trả `{status, env, provider}` |
| `POST /v1/auth/register` | `201` | Public; rate limit 10/phút; cấp HttpOnly JWT cookie + CSRF cookie |
| `POST /v1/auth/login` | `200` | Public; rate limit 10/phút; Argon2id verify; cấp JWT + CSRF cookie |
| `POST /v1/auth/logout` | `204` | CSRF; rate limit 30/phút; xóa JWT + CSRF cookie |
| `GET /v1/auth/me` | `200` | Authenticated; trả `{id, email, displayName, xp}` *(lưu ý: path thực tế là `/v1/auth/me`, không phải `/v1/me`)* |

### 1.2 Courses, Interview, Proposal, Generation, Lessons & Attempts (11 endpoints — `api/v1/routes.py`)

| Method & path | Status | Auth / CSRF / Ghi chú |
|---|---|---|
| `POST /v1/courses` | `201` | Authenticated + CSRF; `{topic: 1..200, clientCourseId: 8..64}` (idempotent) |
| `GET /v1/courses` | `200` | Authenticated; `?limit=&offset=`, owner-scoped |
| `GET /v1/courses/{course_id}` | `200` | Owner (404 cross-user); trả `CourseDetailOut` (`units`, `lessons`, `progress`) |
| `GET /v1/courses/{course_id}/interview` | `200` | Owner; trả `{questions[5], completedCount}` |
| `POST /v1/courses/{course_id}/interview/answer` | `200` | Owner + CSRF; `{position: 0..4, answer: 1..2000}` |
| `GET /v1/courses/{course_id}/proposal` | `200` | Owner; trả `{version, approved, payload}` (`learnerProfile`, `skills`, `prerequisites`, `units`, `outcomes`) |
| `POST /v1/courses/{course_id}/approve` | `202` | Owner + CSRF; pin version, tạo active job `queued` |
| `POST /v1/courses/{course_id}/retry` | `202` | Owner + CSRF; tạo job mới khi course `failed` |
| `GET /v1/courses/{course_id}/generation` | `200` | Owner; trả `GenerationOut` (`status`, `stage`, `lessonsDone`, `lessonsTotal`, `attempts`, `dispatched`, `llmCalls`, `promptTokens`, `completionTokens`, `costEstimateUsd`, `costKnown`) |
| `GET /v1/lessons/{lesson_id}` | `200` | Owner; `public_block()` không bao giờ lộ answer key; trả `grounding`, `citations[]`, `evidenceNotice` |
| `POST /v1/lessons/{lesson_id}/attempts` | `201` | Owner + CSRF; `{clientAttemptId, contentVersion, durationMs?, answers: [{index, answer}]}` (idempotent; `409` nếu stale `contentVersion`; `reviewCardCreated` khi P5.0 bật) |

### 1.3 AI Tutor — SSE & Controls (5 endpoints — `api/v1/tutor.py`, flag `TUTOR_ENABLED=false`)

| Method & path | Status | Auth / CSRF / Ghi chú |
|---|---|---|
| `POST /v1/courses/{course_id}/tutor/messages` | `200` SSE | Owner + CSRF + rate limit; `{clientMessageId, threadId?, text, contextRef:{lessonId, blockIndex}}` (`extra=forbid`); `text/event-stream` (`delta`, `tool`, `done`, `error`, `cancelled`, `heartbeat`) |
| `POST /v1/courses/{course_id}/tutor/messages/{message_id}/stop` | `200` | Owner + CSRF; best-effort cancel (`providerStopGuaranteed: false`), 404 `TUTOR_STOP_NOT_FOUND` |
| `GET /v1/courses/{course_id}/tutor/usage` | `200` | Owner; không tiêu quota; trả `{courseId, windowSeconds, used, limits, remaining, runningStreams, tokensKnown}` |
| `GET /v1/courses/{course_id}/tutor/threads` | `200` | Owner; `?limit=&offset=` |
| `GET /v1/courses/{course_id}/tutor/threads/{thread_id}` | `200` | Owner; lịch sử + `replaySupported: false` |

### 1.4 Sources, Ingestion, Hybrid RAG & OCR (15 endpoints — `api/v1/sources.py`)

| Method & path | Status | Auth / CSRF / Ghi chú |
|---|---|---|
| `POST /v1/sources` | `201` | Authenticated + CSRF; đăng ký metadata nguồn |
| `GET /v1/sources` | `200` | Authenticated; danh sách nguồn thuộc user/public |
| `GET /v1/sources/discover` | `200` | Authenticated; discovery offline (`curated`/`mock`) |
| `GET /v1/sources/ingest-config` | `200` | Authenticated; cấu hình công khai cho UI (ingest, embedding, RAG, web, OCR — không lộ secrets) |
| `GET /v1/sources/{source_id}` | `200` | Owner/accessible |
| `GET /v1/sources/{source_id}/evaluation` | `200` | Owner; đánh giá nguồn theo tiêu chí |
| `DELETE /v1/sources/{source_id}` | `204` | Owner + CSRF |
| `POST /v1/courses/{course_id}/sources` | `201` | Owner + CSRF; liên kết source vào course |
| `GET /v1/courses/{course_id}/sources` | `200` | Owner; danh sách nguồn đã gắn + `groundingAvailable`/`contentIngested` |
| `POST /v1/sources/{source_id}/document` | `202` | Owner + CSRF; upload PDF stream (max 20 MB, 300 trang, MinIO/S3 private) |
| `POST /v1/sources/{source_id}/web-document` | `202` | Owner + CSRF; `{url? \| arxivId?, userConfirmedRights: true, title?}` (`WEB_INGEST_ENABLED=false`) |
| `GET /v1/sources/{source_id}/documents` | `200` | Owner; danh sách documents & trạng thái ingest/OCR |
| `GET /v1/sources/{source_id}/documents/{document_id}` | `200` | Owner; chi tiết document (không trả raw text hay `storage_key`) |
| `DELETE /v1/sources/{source_id}/documents/{document_id}` | `204` | Owner + CSRF |
| `POST /v1/courses/{course_id}/sources/search` | `200` | Owner + CSRF; `{query, sourceIds?, topK}` → `RagSearchOut` (`RAG_ENABLED=false` → 503) |

### 1.5 Source Research Agent (4 endpoints — `api/v1/research.py`, flag `SOURCE_RESEARCH_ENABLED=false`)

| Method & path | Status | Auth / CSRF / Ghi chú |
|---|---|---|
| `POST /v1/courses/{course_id}/research-runs` | `201` | Owner + CSRF; `{maxSources, learningGoals?, learnerLevel?}` (`extra=forbid`) |
| `GET /v1/courses/{course_id}/research-runs` | `200` | Owner; `?limit=&offset=` |
| `GET /v1/courses/{course_id}/research-runs/{run_id}` | `200` | Owner |
| `POST /v1/courses/{course_id}/research-runs/{run_id}/accept` | `200` | Owner + CSRF; chấp nhận nguồn đã chọn để liên kết vào course |

### 1.6 Learner Mastery, Learning Path, FSRS & Exposure (5 endpoints — `api/v1/learner.py`, flag `P50_ENABLED=false`)

| Method & path | Status | Auth / CSRF / Ghi chú |
|---|---|---|
| `GET /v1/courses/{course_id}/mastery` | `200` | Owner; `MasteryOut` (`method="rule_based"`, `coursePercent`, `reviewDueCount`) |
| `GET /v1/courses/{course_id}/learning-path` | `200` | Owner; `LearningPathOut` (`nextLesson`, `blockedBy`, `prerequisitesDag`, `recommendationToken?`) |
| `POST /v1/courses/{course_id}/recommendation-events` | `200` | Owner + CSRF; `{recommendationToken}` (`extra=forbid`; flag `P52_EXPOSURE_ENABLED=false`) |
| `GET /v1/reviews/due` | `200` | Authenticated; `?courseId=&limit=`, hàng đợi FSRS đến hạn |
| `POST /v1/reviews/{card_id}/grade` | `200` | Owner + CSRF; `{rating: 1..4, clientReviewId, durationMs?}` (idempotent) |

## 2. Core request shapes (đối chiếu Pydantic `schemas.py`)

### Create course
```json
{"topic": "Python cho người mới", "clientCourseId": "uuid-from-client"}
```

### Submit attempt (`POST /v1/lessons/{lessonId}/attempts`)
```json
{
  "clientAttemptId": "attempt-uuid",
  "contentVersion": 1,
  "durationMs": 42000,
  "answers": [{"index": 1, "answer": 2}]
}
```
- `AttemptAnswer` đặt `extra="forbid"` và từ chối `bool` ở trường `answer` (tránh coerce `true → 1`).
- Server luôn bỏ qua/từ chối mọi trường `correct`/`score` tự gửi; trả `409` nếu stale `contentVersion`, `422` nếu schema sai.

## 3. HTTP semantics & error codes

- `201` tạo resource mới; `200` đọc/xử lý/replay; `202` job/ingest accepted; `204` xóa/logout; `401` unauthenticated; `403` CSRF/forbidden; `404` không tồn tại hoặc cross-owner; `409` conflict (`JOB_ALREADY_ACTIVE`, stale `contentVersion`, `MESSAGE_IN_PROGRESS`); `413` vượt kích thước file; `422` validation failed (`TUTOR_CONTEXT_INVALID`, thiếu `userConfirmedRights`); `429` rate limit / tutor quota (`TUTOR_LIMIT_REACHED`, `TUTOR_TOKEN_LIMIT_REACHED`, `TUTOR_CONCURRENCY_LIMIT`); `503` feature flag tắt hoặc cấu hình thiếu (`TUTOR_DISABLED`, `RAG_NOT_ENABLED`, `STORAGE_NOT_CONFIGURED`, `PROVIDER_NOT_CONFIGURED`, `EMBEDDING_NOT_CONFIGURED`, `OCR_NOT_CONFIGURED`).

## 4. Idempotency & concurrency matrix

| Operation | Idempotency key / invariant | Quy tắc |
|---|---|---|
| Create course | `(userId, clientCourseId)` | Retry trả lại cùng course |
| Submit attempt | `(lessonId, userId, clientAttemptId)` | Replay cùng kết quả & `xpEarned`, không nhân XP |
| Approve | `(courseId, activeJob)` + pinned `proposalVersion` | Concurrent approve không tạo 2 active jobs |
| Generation job | `generationJobId` + atomic claim + lease | Redelivery no-op; upsert ổn định |
| Tutor message | `(userId, threadId, clientMessageId)` | Completed → replay không gọi LLM; running → `409 MESSAGE_IN_PROGRESS` |
| Source ingest | `(sourceId, checksum, pipelineVersion)` | Retry không nhân chunks |
| FSRS grade | `(userId, cardId, clientReviewId)` | Replay không tính lại lịch hai lần |
| Exposure log | Version-scoped dedupe trên signed token | Không ghi khống hoặc ghi trùng |

## 5. API evolution policy

- Mọi thay đổi contract phải cập nhật đồng bộ `schemas.py`, `frontend/src/lib/api.ts` và spec trong cùng PR.
- Không lộ raw provider error, secrets, prompt hay stacktrace trong response/logs.
- Mọi mutating endpoint dùng cookie auth bắt buộc gọi `verify_csrf(request)`.

## 6. Đối chiếu contract tham chiếu PolySkill (2026-11-22 — `OBSERVED_STATIC`, `PROPOSAL`)

Đợt reverse bằng Craft Anything `0.6.1` (`polyskill-analysis-report.md`) ghi nhận thêm các mẫu contract ở sản phẩm tham chiếu để cân nhắc **additive** ở các phase sau (chưa cam kết triển khai, không phá contract SopiSkill hiện hành):

- **Header đàm phán tính năng:** `x-client-platform` và `x-client-blocks` (`GAP-19`).
- **Short-answer AI grading & dispute:** `POST /v1/lessons/{id}/blocks/{index}/grade` (`got_it | almost | not_yet`, `keyPoints[]`, `feedback`) và `POST /v1/lessons/{id}/grades/{gradeId}/dispute` (`GAP-11`); giữ nguyên chính sách server-authoritative của SopiSkill cho `mc`/`blank`/`order`/`match`.
- **Proposal revision qua Tutor:** `PlanChat` (`entryPoint: 'proposal'`) + tool `revise_proposal` hoặc `PATCH /proposal` versioned (`GAP-08`).
- **Confirmable Tutor Action:** SSE `confirm` + `POST /v1/courses/{id}/tutor/actions/{actionId}/{confirm|decline}` cho `regenerate_unit` (`GAP-20`).
- **Mở rộng bài học & người dùng:** `GET /v1/courses/{id}/glossary`, `lesson.terms[]`, `lesson.estimatedMinutes`, `lesson.format`, `teach.figure` (`formula`/`table`/`visual`/`diagram`), `lesson.reel`, `GET /v1/me/stats`, `PATCH/DELETE /v1/me` tách `appLanguage`/`lessonLanguage` (`GAP-01`..`GAP-23` trong `docs/frontend-reference/api-gap-register.md`).
