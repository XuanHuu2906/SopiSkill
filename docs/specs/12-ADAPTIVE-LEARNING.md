# 12 — Learner Profile, Skill Mastery, FSRS & Conditional ML

**Trạng thái (`2026-11-22`):**
- **P5.0 (Skill Mastery baseline + FSRS `/review` + Learning Path DAG):** **IMPLEMENTED · REPORTED TESTED** (`0015_p50_learner_profile`, `backend/app/api/v1/learner.py`, `frontend/src/app/review/page.tsx`), hiện **DEFAULT-OFF** (`P50_ENABLED=false`).
- **P5.1 (BKT):** **IMPLEMENTED · REPORTED TESTED (research-only)** — **DEPLOY BLOCKED** do thiếu dữ liệu thật (`23-P51-BKT.md`).
- **P5.2 (Adaptive Readiness + Exposure Logging):** **IMPLEMENTED · REPORTED TESTED** — readiness **BLOCKED** cho DKT/bandit; exposure logging (`0016_p52_exposure`) **DEFAULT-OFF** (`P52_EXPOSURE_ENABLED=false`, `24-P52-ADAPTIVE-READINESS.md`).

> **Lợi thế kiến trúc của SopiSkill:** So với phân tích tĩnh PolySkill ngày `2026-11-22` (không có dấu vết BKT/IRT/FSRS phía client; cá nhân hóa nhìn thấy là LLM-driven), SopiSkill đã xây sẵn toàn bộ khung toán học FSRS + Skill DAG + BKT eval + Exposure logging một cách kỷ luật và không phóng đại năng lực ML.

## 1. Core principle

Cá nhân hóa ban đầu dựa trên **5 câu interview (`LearnerProfile`), prerequisite DAG và kết quả quiz thật**; mastery baseline dùng luật minh bạch (`method="rule_based"`), ôn tập cách quãng dùng FSRS từ review event thật, và tuyệt đối không triển khai BKT/DKT/bandit khi dữ liệu thực chưa vượt qua held-out gate.

## 2. Requirements

| ID | Description | Trạng thái (2026-11-22) |
|---|---|---|
| ADAPT-001 | Skill IDs ổn định (`skills`, `lesson_skills`), map vào outcomes + prerequisites DAG | **IMPLEMENTED · TESTED** (`0015`) |
| ADAPT-002 | Mastery baseline rule-based (`skill_mastery`) có trọng số recency từ attempts | **IMPLEMENTED · TESTED** (`P50_ENABLED=false`) |
| ADAPT-003 | Gợi ý bài tiếp theo (`GET /v1/courses/{id}/learning-path`) kèm `blockedBy` & lý do minh bạch | **IMPLEMENTED · TESTED** (`P50_ENABLED=false`) |
| ADAPT-004 | FSRS (`fsrs` 6.3.x, `review_cards`, `review_events`, `/review`) idempotent theo `clientReviewId` | **IMPLEMENTED · TESTED** (`P50_ENABLED=false`) |
| ADAPT-005 | UI hiển thị lý do gợi ý, không khóa cứng khóa học và nói rõ trạng thái khi cờ tắt (503) | **IMPLEMENTED** |
| ADAPT-006 | BKT thuần Python + extractor + held-out eval (Brier/log loss/AUC/ECE/drift) | **IMPLEMENTED (research-only) · DEPLOY BLOCKED** (`0` chuỗi ≥5 event trên DB thật) |
| ADAPT-007 | DKT/LSTM/contextual bandit readiness + HMAC exposure logging (`recommendation_events`) | **READINESS BLOCKED · EXPOSURE IMPLEMENTED (flag OFF, `opeSupported=false`)** |

## 3. P5.0 Rule-based Mastery & FSRS (IMPLEMENTED — `P50_ENABLED=false`)

- **Endpoints:** `GET /v1/courses/{id}/mastery`, `GET /v1/courses/{id}/learning-path`, `GET /v1/reviews/due`, `POST /v1/reviews/{cardId}/grade`.
- **Tham số cấu hình (`config.py`):** `MASTERY_PASS_THRESHOLD=0.7`, `MASTERY_RECENCY_HALF_LIFE_DAYS=30`, `FSRS_DESIRED_RETENTION=0.9`, `P50_BACKFILL_ENABLED=false`.
- `stability`/`difficulty` nội bộ của FSRS cố tình **không** trả ra API để tránh gây hiểu nhầm là điểm số người học; không tự tạo synthetic review events từ quiz lịch sử.

## 4. P5.1 BKT & P5.2 Readiness / Exposure (IMPLEMENTED — RESEARCH / BLOCKED)

- **BKT (`backend/app/services/bkt.py`, `backend/evals/bkt_eval.py`):** 4 tham số, mục tiêu mềm `score_correct/score_total`, kiểm leakage & chronological drift; runtime vẫn trả `method="rule_based"`.
- **Readiness (`backend/evals/p52_readiness.py`):** đo ngưỡng dữ liệu thực (`usersGe10 ≥ 500`, `sequencesGe5 ≥ 200`, `exposures ≥ 5000`); hiện tại `0 / 0 / 0` ⇒ **BLOCKED**.
- **Exposure logging (`POST /v1/courses/{id}/recommendation-events`):** chỉ chấp nhận `recommendationToken` ký HMAC do server phát (`P52_TOKEN_TTL_SECONDS=900`, `extra="forbid"`, version-scoped dedupe). Do policy deterministic nên `propensity=1.0` và `opeSupported=false`.

## 5. Điều kiện kích hoạt tiếp theo

- Bật `P50_ENABLED=true` (và tùy chọn `P52_EXPOSURE_ENABLED=true`) trên môi trường dev/staging sau quyết định của owner để bắt đầu thu thập dữ liệu học & review thật.
- Chỉ mở lại gate BKT/DKT khi dữ liệu thực vượt ngưỡng readiness và chứng minh vượt baseline trên held-out split.
