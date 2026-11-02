# Development Progress

> Ghi nhận trạng thái thực tế. Quy ước: **IMPLEMENTED** (có code) / **TESTED** (đã chạy và pass) / **NOT TESTED** (chưa chạy).

## 2026-11-02 — P5.1 Bayesian Knowledge Tracing (research-only)

- Base commit: `e4f9017` (branch `feat/p5.0-learner-profile`); branch `feat/p5.1-bkt-research` (chưa push)
- Scope & decisions (người dùng đã chốt):
  - **Research-only offline**: không route, không feature flag runtime, không migration,
    không bảng prediction, không worker shadow. API mastery **giữ** `method="rule_based"`.
  - **Dữ liệu thật chưa đủ** ⇒ mục tiêu trung thực là dựng hạ tầng đo và công bố
    `INSUFFICIENT_DATA`, không phải tuyên bố BKT tốt hơn baseline.
  - **Mục tiêu so sánh là điểm mềm** `y = score_correct/score_total` cho **cả** BKT và
    baseline (tránh so lệch mục tiêu mềm vs nhị phân); Brier = `(p-y)^2`.
  - **Baseline as-of** theo từng mốc thời gian (trọng số `0.5^(age/30d)` trên event
    trước đó cùng chuỗi), **không** gọi `compute_mastery(now=...)` ⇒ không nhìn tương lai.
  - **Chỉ attempt khớp `contentVersion`** (`score_total>0`) được dùng, đồng bộ policy P1.1/P5.0.
  - **Extractor read-only**, không `create_all` (khác `rag_eval.py`): bảng skill luôn tồn tại
    nếu tạo bảng, sẽ che mất schema cũ. Phát hiện bảng bằng
    `run_sync(inspect)` vì `inspect(AsyncEngine)` không hợp lệ.
  - **Không thêm dependency**: BKT/AUC/ECE viết pure Python (`numpy`/`sklearn` không có
    trong `requirements.txt`).
- IMPLEMENTED:
  - `backend/app/services/bkt.py`: `BktParams`, `validate`, `observe` (Bayes mềm),
    `apply_learning`, `predict_correct`, `predict_sequence` (không leakage),
    `brier`, `fit_grid` (grid cố định, deterministic).
  - `backend/evals/mastery_dataset.py`: `Sequence`, `DatasetReport`, `redact_dsn`,
    `detect_tables`, `load_sequences` (fallback skill→lesson, DB rỗng an toàn),
    `summarize`.
  - `backend/evals/bkt_eval.py`: `split_by_user`, `split_by_time`, `evaluate`
    (Brier/log loss/AUC/ECE/drift/leakage), `simulate`, `decide_gate`, CLI
    `--dataset real|simulated`, `--save`, `--json`.
  - Tests: `test_p51_bkt.py` (11), `test_p51_dataset.py` (7), `test_p51_eval.py` (17).
  - Docs: `docs/specs/23-P51-BKT.md` (mới), `docs/specs/12-ADAPTIVE-LEARNING.md`,
    `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` mục 3 + 18.
- TESTED (offline, SQLite in-memory):
  - `cd backend && python -m pytest -q` → **635 passed, 28 skipped** (trước 600/28; +35).
  - `python -m pytest tests/test_p51_bkt.py tests/test_p51_dataset.py tests/test_p51_eval.py -q`
    → **35 passed** (không cần PostgreSQL/network).
  - `git diff --stat e4f9017 -- backend/app/models backend/alembic backend/app/api
    backend/app/core/config.py backend/app/services/learner_profile_service.py
    backend/app/services/learning_path_service.py backend/requirements.txt frontend`
    → **rỗng** (chứng minh không đổi runtime/schema/dependency).
- TESTED (PostgreSQL thật, chỉ SELECT — container `db`, DB `ailp`):
  - `python -m evals.bkt_eval --dataset real --database-url postgresql+asyncpg://ailp:***@127.0.0.1:5433/ailp`
    → `users=21 sequences=21 rawAttempts=127 versionedAttempts=37 skillGranularity=False`;
    `lengthHistogram={'1': 6, '2': 14, '3': 1}`; **`INSUFFICIENT_DATA`** với lý do
    `0 chuỗi ≥5 event` và `37 event < 300`.
  - Đối chiếu `psql` cùng DB: **37** event đúng version, **21** user — khớp extractor.
  - `... --granularity lesson --database-url sqlite+aiosqlite:///./tmp_bkt_check.db`
    → DB rỗng không crash, trả 0 và `INSUFFICIENT_DATA`.
  - `python -m evals.bkt_eval --dataset simulated --seed 20261102 --save`
    → `dataSource=simulated`, 800 event, `brier bkt≈0.0228` vs `baseline≈0.0526`,
    `auc≈0.868`, `ece≈0.026`, `leakage=0`, gate `PASS`; report
    `backend/evals/reports/bkt_simulated_<ts>.json`. **Chỉ chứng minh code đúng.**
  - `... --dataset simulated --force-correct` → gate **`NOT_MET`** (baseline Brier=0,
    ECE vượt ngưỡng, AUC không xác định) ⇒ harness không tự khen.
- NOT TESTED:
  - **BKT trên dữ liệu người học thật** — bất khả thi với 0 chuỗi ≥5 event.
  - **Calibration/fairness kết luận** — slice nhỏ, không đủ n; report chỉ mô tả.
  - Chưa chạy trên schema `0015` có bảng skill thật (DB dev vẫn `0012`); nhánh skill
    chỉ được test bằng SQLite in-memory trong `test_p51_dataset.py`.
- BLOCKED: deploy BKT (gate #18) — cần ≥30 chuỗi ≥5 event và ≥300 event đúng version;
  cần quyết định sản phẩm về việc hiển thị "dự đoán" cho người học.
- Database: **N/A** — không migration, không ghi dữ liệu.
- Security: extractor chỉ SELECT; DSN in ra đã che mật khẩu; không log nội dung bài học;
  không có endpoint/route mới; không mở đường đọc chéo user (script chạy cục bộ, không serve).
- Regressions: 0 — 600 test cũ vẫn pass; không file runtime bị sửa.
- Review toàn branch (fresh reviewer) đã tìm và sửa trong cùng phase (635 pytest):
  - **C1** gate không thực thi `min_sequences` đúng nghĩa: dùng `max(10, min//3)` và chỉ
    kiểm tổng event ⇒ 30 chuỗi train dài + 10 chuỗi test 1-event vẫn có thể PASS. Nay gate
    đếm **chuỗi đủ dài riêng từng phía** (`nQualifyingTrain/Test`) + tổng ≥ `min_sequences`.
  - **C2** `driftBrier` chia theo vị trí list (thứ tự user/key), không theo thời gian, và
    `split_by_time` là dead code. Nay `chronological_drift` sắp theo timestamp trước khi chia.
  - **C3** baseline hard-code half-life 30d trong khi runtime dùng
    `MASTERY_RECENCY_HALF_LIFE_DAYS`; nay đọc setting, ghi vào report, có `--baseline-half-life-days`.
  - **C4** quảng cáo fairness slice và "báo cả hai split" nhưng chưa có code; nay thêm
    `slices` (short/long, chỉ mô tả) và ghi rõ CLI mới chạy split theo user.
  - **C5** test chống leakage quá yếu (chỉ so index 0); nay đột biến từng vị trí k và assert
    toàn bộ prefix `< k` không đổi.
  - **C6** test "mismatched model" không assert gate; nay assert `NOT_MET`.
  - **C7** `LEFT JOIN lesson_skills` nhân đôi event khi một bài gắn nhiều skill (data
    inflation) — nay `MIN(s.key)` + `GROUP BY a.id`, có test đếm event.
  - **C8** `redact_dsn` có thể lộ mật khẩu percent-encoded; nay dựng lại netloc từ thành
    phần đã parse, có test `p%40ss`.
  - **C9** tài liệu gọi simulation PASS là "chứng minh code đúng" ⇒ hạ xuống "chứng minh tự
    nhất quán của đường ống", nhấn mạnh chiều `--force-correct` mới là bằng chứng không tự khen.
- Known limitations:
  - Mục tiêu mềm (`k/5`) khác BKT nhị phân cổ điển, chọn để so cùng đại lượng với mastery.
  - 1 skill/bài (kế thừa P2.1) ⇒ chuỗi skill thực chất là chuỗi bài.
  - `skills.key` chỉ ổn định trong một course ⇒ không gộp chuỗi xuyên course.
  - `question`-level (`results`) chưa map skill nên chưa dùng trong gate.
  - Baseline trong harness là bản tái lập `compute_mastery`; nếu đổi baseline runtime
    phải cập nhật song song, nếu không so sánh sẽ sai.
- PHASE GATE: **GATE-PARTIAL** — code + test + số liệu thật đầy đủ, nhưng gate deploy
  là **BLOCKED** vì dữ liệu chưa đủ (đúng điều kiện của plan, không phải lỗi triển khai).
- NEXT: tích luỹ dữ liệu attempt (đặc biệt user có ≥5 bài cùng skill) rồi chạy lại
  `evals.bkt_eval --dataset real`; hoặc chuyển P6 (production hardening).

## 2026-11-02 — P5.0 Learner Profile, Mastery Baseline & FSRS

- Base commit: `2150b0d` (`feat/p4.3-ocr`); branch `feat/p5.0-learner-profile` (chưa push)
- Scope & decisions (người dùng đã chốt):
  - **Snapshot bền vững + thư viện `fsrs`** (không tự viết lại thuật toán), pin
    `FSRS_SCHEDULER_VERSION = "py-fsrs-6.3.2"` vào từng card/event.
  - **Review card tạo ngay ở attempt đầu tiên** (kể cả <80%) ⇒ rating `Again/Hard`
    là luồng thật (ôn bài yếu), không phải code chết.
  - **1 card/(user, lesson)**, recall theo **chủ đề bài + skill** — không lộ answer key quiz.
  - **Mastery = accuracy có trọng số thời gian** (half-life 30 ngày), ngưỡng đạt `0.7`.
    Đây là **heuristic**, KHÔNG phải xác suất đã hiệu chuẩn; API trả `method="rule_based"`.
  - **`contentVersion` đổi ⇒ không reset mastery**: mastery chỉ tính attempt đúng version
    hiện hành nên tự rơi về 0 cho tới khi có attempt mới; dữ liệu cũ giữ nguyên.
  - **Prerequisite chưa đạt ⇒ CHẶN bài mới** + trả `blockedBy` kèm lý do, và fallback
    `reviewLessonId` = bài đã học có mastery thấp nhất (tránh dead-end).
  - **Skill map theo VỊ TRÍ** `(unit.order_index, lesson.order_index)`, không theo title —
    generation ghi đè `lesson.title` bằng `content.title` của provider.
  - **`learning_steps=()`** ⇒ card vào thẳng `State.Review`, lịch theo ngày
    (đo thật với `fsrs` 6.3.2: Again 1d / Hard 1d / Good 2d / Easy 8d),
    `enable_fuzzing=False` để tái lập.
- IMPLEMENTED:
  - `backend/requirements.txt`: `fsrs>=6.3,<7` (pure Python, chỉ kéo `typing-extensions`;
    optimizer extras KHÔNG cài).
  - `backend/app/core/config.py`: `p50_enabled`, `p50_backfill_enabled`,
    `mastery_pass_threshold`, `mastery_recency_half_life_days`, `fsrs_desired_retention`.
  - `backend/app/models/models.py` + `models/__init__.py`: `Skill`, `LessonSkill`,
    `SkillMastery`, `ReviewCard`, `ReviewEvent`.
  - `backend/alembic/versions/0015_p50_learner_profile.py` (expand-only, downgrade đối xứng).
  - `backend/app/services/learner_profile_service.py`: `backfill_course_skills`,
    `skills_for_course`, `skill_for_lesson`, `compute_mastery`, `refresh_skill_mastery`,
    `course_mastery`, `backfill_all_skills`, `_as_utc`.
  - `backend/app/services/spaced_repetition_service.py`: `scheduler`, `new_card`, `review`,
    `initial_rating`, `ensure_card_for_attempt`, `grade_card`, `due_cards`, `_card_id`.
  - `backend/app/services/learning_path_service.py`: `build_learning_path`, `position_key`,
    reason codes `NEXT_IN_SEQUENCE`/`PREREQUISITES_MET`/`PREREQUISITE_NOT_MET`/
    `FALLBACK_REVIEW_WEAKEST`.
  - `backend/app/services/lesson_service.py`: `submit_attempt` trả 3-tuple, cập nhật mastery
    + tạo card trong **cùng transaction** khi `P50_ENABLED`.
  - `backend/app/api/v1/learner.py` + `main.py`: 4 endpoint, 503 `P50_NOT_ENABLED` khi tắt.
  - `backend/app/worker/generation.py`: backfill skill sau generation (lỗi không làm job fail).
  - `backend/app/worker/reconcile.py` + `celery_app.py`: task `reconcile_skills` trên beat,
    chỉ chạy khi `P50_BACKFILL_ENABLED`.
  - Frontend: `lib/api.ts` (5 hàm + types), khối "Học tiếp"/"Ôn tập"/"Mức nắm kỹ năng" ở
    `/course/[courseId]`, trang mới `/review` (hàng đợi, reveal, 4 mức rating, một
    `clientReviewId` mỗi lần chấm), thông báo "Đã thêm vào lịch ôn tập" ở lesson.
  - `backend/e2e_acceptance.py`: check `8e`/`8f`/`8g` (503 khi tắt; mastery rule-based;
    learning-path có lý do; review grade idempotent).
  - Docs: `docs/specs/22-P50-LEARNER-PROFILE.md`, plan
    `docs/superpowers/plans/2026-11-02-p50-learner-profile.md`, `database-design.md`,
    `migration-runbook.md`, `.env.example`, `docker-compose.yml` (3 service).
- TESTED (offline, SQLite in-memory):
  - `cd backend && python -m pytest -q` → **597 passed, 25 skipped** (trước 540/25; +57).
    Mới: `test_p50_config.py` (2), `test_p50_migration_contract.py` (5), `test_p50_skills.py` (6),
    `test_p50_mastery.py` (11), `test_p50_fsrs.py` (16), `test_p50_learning_path.py` (5),
    `test_p50_api.py` (9), `test_p50_generation_hook.py` (3).
  - Phủ: FSRS interval chính xác cho 4 rating; ép UTC cho datetime naive; card tạo ở attempt
    đầu (kể cả `score_total=0`); idempotency theo `clientReviewId`; cross-user ⇒ 404;
    mastery deterministic + không tăng khi nộp lại cùng version; version mới ⇒ không còn
    attempt hợp lệ (row cũ giữ nguyên); backfill theo vị trí khi title khác; slug trùng ⇒
    hậu tố deterministic; backfill không xoá mastery; prerequisite chưa đạt ⇒ chặn + fallback;
    cờ tắt ⇒ 503; CSRF 403; rating ngoài 1..4 ⇒ 422.
  - `cd frontend && npx tsc --noEmit` → 0 lỗi; `npm run build` → OK (11 route, thêm `/review`).
  - `docker compose config` → OK (biến P50 có ở backend/worker/beat).
- TESTED (PostgreSQL throwaway `p50_migration_check`, đã `DROP DATABASE`):
  - `alembic upgrade head` → `0015_p50_learner_profile (head)`; `skills` có
    `uq_skill_course_key` + FK CASCADE; `review_cards` có `uq_review_card_user_lesson`,
    `ix_review_cards_user_due`, FK `lesson_attempts ON DELETE SET NULL`;
    `review_events` có `uq_review_event_client_id` + 2 index composite.
  - `downgrade -1` → `0014_p43_ocr`; 5 bảng biến mất, `users`/`lessons` **còn 1/1**;
    `upgrade head` lại thành công, row legacy đọc được.
- TESTED (PostgreSQL throwaway `p50_race_check`, đã drop):
  - `POSTGRES_TEST_URL=…/p50_race_check python -m pytest tests/test_p50_postgres_concurrency.py -q`
    → **3 passed** (tạo card đồng thời, grade đồng thời, cross-user grade).
  - Full suite sau khi thêm file này: **600 passed, 28 skipped** (25 skip cũ + 3 skip khi
    không có `POSTGRES_TEST_URL`).
- NOT TESTED:
  - **E2E Docker full stack** với `P50_ENABLED=true` — chưa chạy `e2e_acceptance.py` trong
    phiên này (stack chỉ bật container `db`); các check `8e/8f/8g` mới chỉ được review tĩnh.
  - ~~Race PostgreSQL cho review grade/`ensure_card_for_attempt`~~ — **đã chạy** (xem mục
    TESTED PostgreSQL bên dưới); vẫn chưa chạy E2E Docker có worker thật.
  - **Chất lượng sư phạm thật** của mastery/ngưỡng 0.7: chưa có dữ liệu học thật để hiệu
    chuẩn; các ngưỡng là PROPOSAL.
  - Browser E2E (Playwright) cho `/review`.
  - `fsrs` optimizer / cá nhân hoá tham số (cố ý không dùng).
- BLOCKED: không blocked code. Cần quyết định vận hành: có bật `P50_ENABLED=true` ở production
  ngay không (thay đổi UX + ghi dữ liệu mới), và có chạy `P50_BACKFILL_ENABLED` một lần cho
  course cũ hay để course mới tự sinh skill.
- Database: `0015_p50_learner_profile` (expand-only). Backup trước trên DB thật:
  `docker compose exec db pg_dump -U ailp ailp > backup_pre_p50_YYYYmmdd_HHMMSS.sql`.
- Security: ownership ở SQL (course/card ⇒ 404); mastery tính từ attempt đã lưu, không nhận
  score từ client; rating client chỉ là input FSRS, không ảnh hưởng XP/điểm; CSRF + rate limit
  120/60s cho grade; `stability/difficulty` **không** trả ra API người học; log chỉ id + interval.
- Regressions: 0 — 540 test cũ vẫn pass; `submit_attempt` chỉ đổi tuple khi `P50_ENABLED`,
  contract HTTP thêm field additive `reviewCardCreated` (mặc định false).
- Known limitations:
  - Mastery không phân biệt độ khó câu hỏi, không hiệu chuẩn xác suất, chưa tính
    `duration_ms`.
  - `review_cards` 1 card/lesson: không ôn theo từng block/câu sai.
  - Chưa có notify/push/email nhắc ôn; due date hiển thị theo giờ máy người dùng.
  - `fsrs` chạy in-process; chưa có job dọn card/event cũ.
- Review toàn branch (fresh reviewer) đã tìm và sửa trong cùng phase (600 pytest):
  - **C1** `ensure_card_for_attempt` rollback toàn session khi race ⇒ mất attempt: đổi sang
    SAVEPOINT (`db.begin_nested()`), lỗi P5.0 không còn phá transaction attempt.
  - **C2** slug trùng làm mất skill đầu + map sai lesson: `_dedupe_keys` trả list song song
    theo vị trí, map skill↔lesson theo **index** (không tra title).
  - **I1** đổi `contentVersion` không reset mastery: giờ khi không còn attempt đúng version
    hiện hành, snapshot mastery được ghi `mastery_score=0, attempts=0` (attempt cũ giữ nguyên).
  - **I2** `reviewDueCount` bị chặn bởi `limit`: thêm `COUNT(*)` không phụ thuộc page size.
  - **I3** grade đồng thời mất review: `SELECT ... FOR UPDATE` trên `review_cards`.
  - **I4** test race PostgreSQL P1.1 bị hỏng do `submit_attempt` đổi thành 3-tuple: đã sửa.
  - **I5** test "lesson không skill" chưa thực sự bật cờ: đã bật cờ và assert card `skill_id=None`.
  - **I6** thiếu `skillTitle` trong due reviews: đã thêm (schema + service).
  - **I7** `fsrs>=6.3,<7` có thể lệch với `scheduler_version`: **pin `fsrs==6.3.2`**.
  - **I8** backfill sau generation đọc proposal mới nhất thay vì version job đã pin: truyền
    `proposal_version=job.proposal_version`.
  - Thêm `tests/test_p50_postgres_concurrency.py` và chạy thật trên PostgreSQL throwaway
    (`p50_race_check`, đã drop): 6 task tạo card đồng thời ⇒ **đúng 1 card**, mọi task không
    ném exception (SAVEPOINT giữ attempt), attempt còn 1 row; 4 grade đồng thời khác
    `clientReviewId` ⇒ 5 event, không lost update; cross-user ⇒ `CardNotFoundError`.
- PHASE GATE: **GATE-PARTIAL** — code + offline tests + migration PostgreSQL thật đầy đủ; E2E
  Docker và race PostgreSQL (bao gồm race grade mới) còn NOT TESTED (ghi rõ, không tuyên bố PASS).
- NEXT: chạy E2E Docker với `P50_ENABLED=true` (cần approve), hoặc P6 (production hardening)
  nếu ưu tiên release.

## 2026-11-01 — P4.3 OCR cho PDF scan (opt-in, engine pretrained)

- Base commit: `e3cb783` (`feat/p4.3-ocr`, working tree)
- New commit/branch: branch `feat/p4.3-ocr` — **NOT COMMITTED**
- Scope & decisions:
  - **Mặc định TẮT** (`OCR_ENABLED=false`): hành vi P4.0/P4.2 giữ nguyên; PDF scan vẫn `no_text`.
    Bật cờ mà engine chưa cài/`OCR_MODEL_VERSION` trống ⇒ upload **422 `OCR_NOT_CONFIGURED`**,
    không ghi file, không âm thầm quay về text-only.
  - **Pretrained only**: `rapidocr` (ONNX PP-OCR, CNN det + CNN rec, chạy cục bộ). Không
    train/fine-tune, không gửi tài liệu ra API ngoài. So sánh v6-small/v6-medium (kết quả giống
    nhau), PP-OCRv4/v5 (không hỗ trợ `vi`).
  - **Chỉ OCR trang THIẾU text**; trang native không bị đọc lại ⇒ tài liệu hỗn hợp có
    `textSource=mixed`, chunk native giữ `ocrConfidence=NULL` (không bịa điểm tin cậy).
  - **Provenance**: chunk OCR mang `textSource=ocr`, `ocrConfidence` (điểm engine, **không** phải
    xác suất đúng đã hiệu chuẩn) và `ocrBbox=[x0,y0,x1,y1]` chuẩn hoá theo trang; offset vẫn cắt
    đúng substring text trang.
  - **Bật OCR đổi `pipelineVersion`** (`p4.0-v1+ocr-rapidocr-<ver>`, web: `p4.2-v1+…`) ⇒ document
    cũ (`no_text`) không bị ghi đè, citation cũ giữ đúng dữ liệu đã sinh ra nó.
  - **Fail-closed**: trần `OCR_MAX_PAGES` kiểm TRƯỚC khi chạy engine; `OCR_TIMEOUT`/`OCR_FAILED`
    retryable → `failed`; OCR không đọc được chữ → `no_text` + `OCR_NO_TEXT`.
- IMPLEMENTED:
  - `backend/app/services/ocr.py` (mới): `OcrLine{text,confidence,bbox}`, `OcrPage`, `OcrError`,
    `engine_available`, `configured`, `ocr_pdf_pages` (render pypdfium2 → engine ONNX), cache
    engine có lock, `reset_engine`.
  - `backend/app/services/ingest.py`: `LineSpan`, `ExtractedPage.text_source/line_spans`,
    `ChunkDraft.text_source/ocr_confidence/ocr_bbox`, `pages_without_text`, `build_ocr_pages`,
    `apply_ocr`/`apply_ocr_pages`, `extract_document`, `pipeline_version_for`/`ocr_pipeline_version`,
    `_annotate_provenance`, `finish_ready`/`finish_no_text(code=…)`.
  - `backend/app/worker/ingest.py`: PDF upload và arXiv/PDF fetched dùng chung `extract_document`.
  - `backend/app/services/web_ingest.py`: `pipeline_version_for` cho web/arXiv.
  - `backend/app/services/retrieval_service.py`: `RetrievedChunk.text_source/ocr_confidence`.
  - `backend/app/services/citation_service.py`: citation/pointer có `textSource`, `ocrConfidence`.
  - `backend/app/models/models.py`, `alembic/versions/0014_p43_ocr.py` (expand-only): document
    `text_source|ocr_pages|ocr_engine|ocr_version`; chunk `text_source|ocr_confidence|ocr_bbox`.
  - `backend/app/core/config.py`: 8 cấu hình `OCR_*` + `ocr_configured`.
  - `backend/app/schemas/schemas.py`, `backend/app/api/v1/sources.py`: `textSource/ocrPages/
    ocrEngine/ocrVersion` trong document; `ocrEnabled/ocrConfigured/ocrEngine/ocrVersion/
    ocrMaxPages/ocrDpi` trong ingest-config; `textSource/ocrConfidence/ocrBbox` trong search.
  - `frontend/src/lib/api.ts`, `frontend/src/app/sources/page.tsx`: badge OCR/mixed, notice khi
    OCR tắt, thông điệp trung thực khi `OCR_NO_TEXT`.
  - `backend/requirements-ocr.txt` (mới), `backend/Dockerfile` (`ARG INSTALL_OCR=false`),
    `.env.example`, `docker-compose.yml`, `docs/specs/21-P43-OCR.md` (mới), `docs/specs/
    11-SOURCES-AND-RAG.md`, `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`.
  - `backend/evals/ocr_eval.py` (mới): CER/WER/confidence/latency trên corpus synthetic EN+VI.
  - `backend/tests/scan_fixtures.py`, `backend/tests/test_p43_ocr.py` (O01–O15 + web/upload
    pipeline), `backend/tests/test_p43_migration_contract.py`.
- TESTED (đã chạy trong phiên này):
  - `cd backend && python -m pytest -q` → **534 passed, 25 skipped, 16 warnings** (exit 0). Suite
    gồm 16 test P4.3 + 7 test migration contract; test O15 chạy **engine rapidocr thật** trên PDF
    scan tự sinh.
  - `python -m evals.ocr_eval --lang vi` → 8 case: **CER avg 0.0470** (EN 0.000 / **VI 0.0939**),
    **WER avg 0.2068**, mean confidence 0.9913, detectedPageRate 1.000, **~2770 ms/trang @200 DPI**.
    Model **rơi dấu tiếng Việt** ("Cấu trúc" → "Cu trúc"); thử v6-medium/v4/v5 không cải thiện.
  - `python -m evals.ocr_eval --lang en --language vi` → CER 0.0939, WER 0.4137 (xác nhận lỗi do
    model/ngôn ngữ, không do tham số eval).
  - Migration trên **PostgreSQL tạm** `p43_mig_check` (container `reverseengineer-db-1`, port 5433):
    `alembic upgrade head` → `current` = `0014_p43_ocr` → `downgrade -1` (6 cột biến mất, bảng còn)
    → `upgrade head` → `0014_p43_ocr`. DB tạm đã `DROP DATABASE` sau kiểm tra; **không đụng DB
    chính**.
  - `docker compose config` OK; `docker compose build backend` OK (image mặc định **không** có OCR
    deps ⇒ fail-fast giữ nguyên).
  - `cd frontend && npx tsc --noEmit` OK; `npm run build` OK (10 route).
  - `git diff --check` sạch.
- NOT TESTED:
  - OCR trên **corpus scan thật** (mờ/nghiêng/bảng/công thức/chữ viết tay). Corpus hiện tại là
    synthetic dựng bằng font hệ thống ⇒ không suy rộng CER.
  - Layout-aware parser cho bảng/công thức (chưa làm; chỉ dòng text).
  - E2E Docker full stack với `OCR_ENABLED=true` (image chưa cài `requirements-ocr.txt`).
  - `e2e_acceptance.py` chưa chạy lại trong phiên này (stack Docker không được bật).
- BLOCKED: không. **Quyết định cần người dùng**: có chấp nhận chất lượng tiếng Việt hiện tại
  (mất dấu) cho bật OCR production hay không, và có cho phép cài OCR deps vào image production.
- Database: `0014_p43_ocr` (expand-only, downgrade chỉ drop 6 cột mới). Không backfill document cũ
  (`text_source=NULL` ⇒ tầng đọc coi là `native`).
- Security: không tin client (magic/size/page); text OCR là **untrusted** (vẫn qua `wrap_untrusted`
  khi vào prompt); engine chạy cục bộ, không request outbound; log không chứa nội dung tài liệu;
  cross-user vẫn 404 (O10); config API không lộ credential.
- Regressions: 0 — 518 test cũ vẫn pass, P4.0/P4.2 giữ nguyên hành vi khi OCR tắt.
- Known limitations: xem `docs/specs/21-P43-OCR.md` mục 5.
- PHASE GATE: **PASS (opt-in)** — kèm giới hạn tiếng Việt + corpus synthetic đã công bố.
- NEXT: quyết định bật OCR production (cần corpus thật + chấp nhận sai dấu), hoặc chuyển P5.0/P6.

## 2026-11-01 — P4.2 Web/arXiv Sources (offline + SSRF guard đầy đủ)

- Base commit: `bc78efe` (`main`, working tree)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Outbound mặc định TẮT**: `WEB_INGEST_ENABLED=false` + `WEB_INGEST_ALLOWED_HOSTS` rỗng ⇒
    fail-closed; không có request nào ra ngoài cho tới khi người vận hành bật **và** khai host.
  - **Chống SSRF hai lớp**: (a) resolve DNS trước và yêu cầu MỌI IP `is_global` (chặn private,
    loopback, link-local, metadata, CGNAT, multicast, IPv4-mapped); (b) `PinnedNetworkBackend`
    resolve lại **ngay trong `connect_tcp`** và chỉ mở socket tới IP đã kiểm ⇒ chặn DNS
    rebinding. Mỗi hop redirect chạy lại toàn bộ cổng.
  - **Quyền sử dụng bắt buộc**: `userConfirmedRights=true` (schema 422 nếu thiếu/sai) và lưu
    `source_documents.rights_confirmed_at`. Fetch thành công **không** nâng `verification_status`.
  - **arXiv chỉ nhận ID**; host dựng từ config **và** phải nằm trong allowlist; Atom parse bằng
    `defusedxml`; PDF phải có magic `%PDF-`.
  - **Không đổi stack**: `httpx` + network backend của httpcore; HTML parser là stdlib
    `html.parser`; **không** render HTML nguồn ra browser.
- IMPLEMENTED:
  - `backend/app/core/config.py`: 15 cấu hình `WEB_*`/`ARXIV_*` + `web_allowed_hosts`,
    `web_ingest_active`.
  - `backend/app/services/url_fetcher.py`: `parse_http_url`, `host_allowed`, `ip_is_public`,
    `resolve_host_ips`, `check_ips_public`, `validate_url`, `validate_url_resolved`,
    `PinnedNetworkBackend`, `build_pinned_transport`, robots parser/cache (`_parse_robots`,
    `robots_allows`, `ensure_robots_allowed`), `fetch_resource` (redirect thủ công, trần
    byte/redirect/time, MIME sniffing, mã lỗi ổn định), `WebFetchError`.
  - `backend/app/services/html_extract.py`: `sanitize_extract` (bỏ script/style/iframe/nav/footer/
    form; breadcrumb heading → `section_anchor`; trần ký tự), `HtmlSection`, `section_for_offset`.
  - `backend/app/services/arxiv_service.py`: `normalize_arxiv_id` (new/old style + `vN`),
    `split_version`, `parse_atom` (defusedxml), `fetch_metadata`/`fetch_pdf`,
    `_ensure_hosts_allowed`.
  - `backend/app/services/web_ingest.py`: `register_web_document` (idempotent theo
    `(source, content_hash, web_pipeline_version)`, lưu blob private storage, audit rights, điền
    metadata `Source` chỉ khi trống), `parse_web_extraction`, `chunk_web_extraction` (không
    overlap, offset tuyệt đối, phủ kín text).
  - `backend/app/models/models.py`: `SourceDocumentOrigin`; `source_documents.origin|origin_url|
    origin_meta|rights_confirmed_at`; index `(source_id, origin_url)`.
  - `backend/alembic/versions/0013_p42_web_ingest.py`: expand-only (4 cột + enum + index);
    downgrade chỉ xóa phần thêm.
  - `backend/app/worker/ingest.py`: `_ingest_fetched` — web chunk theo section, arXiv dùng pipeline
    PDF P4.0; dùng chung `finish_ready` + `embed_after_ingest` ⇒ RAG P4.1 chạy không cần sửa.
  - `backend/app/api/v1/sources.py`: `POST /v1/sources/{id}/web-document` (CSRF, rate limit
    5/60s, ownership, rights bắt buộc, map mã lỗi → HTTP 4xx/5xx); ingest-config trả trạng thái
    web/arXiv.
  - `backend/app/schemas/schemas.py`: `WebDocumentRequest` (model_validator: đúng một locator +
    rights), `SourceDocumentOut.origin|originUrl|rightsConfirmed`, ingest-config `web*/arxiv*`,
    `TutorCitationOut.sourceUrl`, `RagChunkOut.sourceUrl`.
  - `backend/app/services/retrieval_service.py` + `citation_service.py`: `RetrievedChunk.source_url`
    lấy từ `SourceDocument.origin_url`; citation trả `sourceUrl` (None với PDF upload).
  - Frontend `frontend/src/lib/api.ts` + `/sources`: form ingest URL/arXiv với checkbox quyền sử
    dụng bắt buộc; badge origin + link nguồn thật; ingest-config mới.
  - `backend/requirements.txt`: `defusedxml>=0.7`.
  - Docs: `docs/specs/11-SOURCES-AND-RAG.md` §7 (viết lại), `database-design.md`,
    `migration-runbook.md` (mục P4.2), master plan (P4.2 DONE + 3 decision log), `.env.example`,
    `docker-compose.yml` (backend/worker/beat).
- TESTED (offline, SQLite):
  - `cd backend && python -m pytest -q` → **507 passed, 24 skipped** (426 → 507, +81).
    Mới: `tests/test_p42_web_ingest.py` (74), `tests/test_p42_migration_contract.py` (7).
  - Phủ: allowlist exact/subdomain (không khớp `evil-example.com`); 12 dạng IP bị chặn; một IP xấu
    chặn cả host; DNS rebinding bị chặn ở `connect_tcp` trước khi mở socket; redirect sang host lạ
    (403) / IP nội bộ (403) / quá trần; MIME lạ; HTML giả nhị phân; vượt byte qua `content-length`
    và qua stream; 429 retryable; robots deny + robots 5xx ⇒ từ chối; robots longest-match; HTML
    độc hại (script/style/nav/footer bị bỏ, text còn); chunk không overlap và phủ kín text;
    rights thiếu ⇒ 422 **và không tạo document**; CSRF thiếu ⇒ 403; cờ tắt ⇒ 503; host ngoài
    allowlist ⇒ 403; cross-user ⇒ 404 (ingest + xóa); public source ⇒ 404; idempotent fetch trả
    cùng document; arXiv ID valid/invalid/old-style/entity-expansion/not-found/PDF-magic; arXiv
    host ngoài allowlist ⇒ 503; citation mang `sourceUrl`; PDF upload không có `sourceUrl`.
- TESTED (PostgreSQL throwaway `p42_migration_check`, đã drop):
  - `alembic upgrade head` → `0013_p42_web_ingest (head)`; `\d source_documents` có 4 cột + enum 3
    value + `ix_source_documents_origin_url btree (source_id, origin_url)`.
  - `alembic downgrade -1` → `0012_p41_rag`: 4 cột + enum + index biến mất, bảng giữ nguyên;
    insert legacy-row ở 0012 rồi `upgrade head` lại ⇒ row cũ `origin='upload'`, `origin_url=NULL`,
    `rights_confirmed_at=NULL` (không bịa dữ liệu).
- TESTED (PostgreSQL throwaway `p42_race_check`, đã drop):
  - `POSTGRES_TEST_URL=…/p42_race_check python -m pytest tests/test_p42_postgres_concurrency.py -q`
    → **1 passed**: 10 lần fetch đồng thời cùng nội dung ⇒ **đúng 1 document** (UNIQUE
    `source_id,content_hash,pipeline_version`), `origin=web` + rights audit; worker ingest ra chunk
    `ready` khớp offset text; ingest lại không nhân bản chunk.
- TESTED (frontend): `npx tsc --noEmit` → 0 lỗi; `npm run build` → OK (`/sources` 5.51 kB).
- TESTED (compose): `docker compose config` → OK (biến `WEB_*` có ở backend/worker/beat).
- TESTED (mạng THẬT, `python scripts/p42_real_e2e.py`, SQLite throwaway, 2026-11-01):
  - **33/33 checks passed.** `example.com` ingest → `ready`, `origin=web`, `chunkCount=1`,
    `rightsConfirmed=true`, `originUrl` đúng, fetch lại idempotent (cùng document id).
  - **arXiv thật `1706.03762`** (Attention Is All You Need): metadata từ trang `/abs` (robots
    cho phép `Allow: /abs`), PDF 2.2 MB, **15 trang, 45 chunk**, `origin=arxiv`,
    `originUrl=https://arxiv.org/abs/1706.03762`, `publisher=arXiv`; `verificationStatus`
    vẫn `unverified` (fetch thành công không đồng nghĩa đã xác thực).
  - Retrieval thật trên chunk arXiv trả 5 item, **mọi item có `sourceUrl`**;
    `verify_answer_citations` trả 2 citation với `sourceUrl` thật và
    `evidenceSupported=false`.
  - Cross-user ingest/xóa ⇒ 404; SSRF chặn thật: `http://169.254.169.254` ⇒ 422
    `WEB_HTTPS_REQUIRED`, `https://169.254.169.254` ⇒ 403 `WEB_HOST_NOT_ALLOWED`,
    `http://127.0.0.1:8000` ⇒ 422, `https://evil.invalid` ⇒ 403.
  - Phát hiện trong lúc chạy: robots của `export.arxiv.org` là `Disallow: /` ⇒ **Atom API mặc
    định bị chặn**. Đã đổi mặc định sang trang `/abs` (Highwire `citation_*`), Atom chỉ bật khi
    đặt `ARXIV_METADATA_SOURCE=atom`. Ghi lại để không ai tưởng API là mặc định.
- NOT TESTED:
  - E2E Docker đầy đủ (backend/worker/frontend) cho P4.2 — container đang stopped (đã chạy
    pytest offline + PostgreSQL race + E2E mạng thật in-process thay thế).
  - robots.txt wildcard `*`/`$`, `Crawl-delay` (chỉ hỗ trợ path-prefix).
  - Trang render bằng JavaScript (SPA): chỉ trích HTML server trả về; không có text ⇒
    `WEB_NO_EXTRACTABLE_TEXT`.
  - Trang render bằng JavaScript (SPA): chỉ trích HTML server trả về; không có text ⇒
    `WEB_NO_EXTRACTABLE_TEXT`.
  - Malware scanning file tải về; citation precision/groundedness ngoài phạm vi (P4.1 eval mở rộng).
- BLOCKED: không blocked code. Cần quyết định vận hành nếu bật ở production: allowlist thật
  (site nào được phép), chính sách robots/licensing, và host ổn định nếu muốn đưa fetch mạng thật
  vào CI (test suite hiện hoàn toàn offline).
- Database: `0013_p42_web_ingest` (expand-only). Backup trước trên DB thật:
  `docker compose exec db pg_dump -U ailp ailp > backup_pre_p42_YYYYmmdd_HHMMSS.sql`.
- Security: outbound fail-closed (allowlist rỗng = deny); IP global-only ở cả validate/connect;
  redirect validate lại từng hop; TLS SNI giữ hostname gốc; `trust_env=False` (không dùng proxy
  env); arXiv host phải nằm trong allowlist; XML parse an toàn; rights audit server-side;
  ownership 404 cross-user; public source không ingest/xóa được; log chỉ id/host/mã lỗi (không URL
  đầy đủ, không nội dung); CSRF + rate limit 5/60s; trần byte/time/redirect.
- Regressions: 0. pytest 426 → **507 passed**; frontend build OK.
- Known limitations:
  - robots.txt chỉ hiểu luật path-prefix; chưa hỗ trợ wildcard `*`/`$` hay `Crawl-delay`.
  - Chưa cache nội dung theo TTL (fetch lại vẫn gọi mạng; chỉ idempotent ở DB).
  - HTML extract là heuristic (không readability scoring); trang nhiều chrome vẫn có thể lẫn text.
  - `origin_meta` lưu metadata HTTP/arXiv — KHÔNG phải bằng chứng nội dung đúng.
- PHASE GATE: **PASS (offline + guard)** — acceptance SSRF/ownership/citation source thực đạt
  bằng test đã chạy; hạng mục "fetch mạng thật" để **NOT TESTED**, không tuyên bố PASS.
- NEXT: P4.3 (OCR, cần corpus scan thật) hoặc P5.0 (Learner Profile/FSRS) tuỳ ưu tiên; trước P4.3
  cần mẫu PDF scan có phép để đánh giá CER/WER.

## 2026-10-31 — P4.1 Hybrid RAG + verified citations (offline baseline)

- Base commit: `9f5b5bf` (`main`, working tree — tiếp nối P4.0 chưa commit)
- New commit/branch: **NOT COMMITTED** (working tree)
- Quyết định (người dùng phê duyệt): **phương án A — offline-first**
  - Embedding mặc định `hashing` (deterministic, không network, không tải model). Đây là baseline
    lexical/subword, **KHÔNG** phải semantic embedding của Transformer.
  - Adapter `openai_compatible` thêm nhưng **mặc định TẮT**; thiếu base URL/key/model/dimension ⇒
    `EMBEDDING_NOT_CONFIGURED`, **không fallback** sang hashing.
  - **Không đổi Docker image**, **không pgvector** ở phase này; vector lưu JSON + cosine exact có trần.
  - Đổi sang pgvector khi benchmark chứng minh cần — xem số đo bên dưới.
- IMPLEMENTED:
  - `backend/app/services/embedding_service.py`: `EmbeddingSpec(provider, model, dimension, version)`,
    `HashingEmbeddingProvider`, `OpenAICompatibleEmbeddingProvider`, `active_spec`,
    `get_embedding_provider` (fail-fast), `hashing_embed` (token + char n-gram + fold dấu, signed hash,
    L2), `cosine_similarity`, `chunks_missing_embedding`/`embed_chunks` (upsert idempotent),
    `embedding_coverage`.
  - `backend/app/services/retrieval_service.py`: scope SQL (course + owner/public + document ready),
    lexical (`to_tsvector('simple')`/`ts_rank_cd` trên PostgreSQL; token-overlap trên SQLite), vector
    cosine đúng spec, `rrf_fuse`, `RetrievedChunk`/`RetrievalResult`, `build_context_section_with_ids`
    (allowlist khớp đúng đoạn đưa vào prompt), `insufficient_evidence`.
  - `backend/app/services/rag_service.py`: `rag_active`, `retrieve_for_question`,
    `build_system_with_rag`, `verify_answer` (verified/unverified/rejected), `embed_after_ingest`,
    `coverage_notice`, `build_tool_read_source_section`, `lesson_query`.
  - `backend/app/services/citation_service.py`: `extract_citation_ids`, `verify_answer_citations`
    (chỉ id trong allowlist của request ⇒ `locator_verified`, `evidenceSupported` luôn False),
    `unverified_source_pointers`.
  - `backend/app/services/tutor_tools.py`: `read_source` **bật thật** qua `execute_async` +
    `SourceReader` callback; `ReadSourceArgs.query`; args summary không ghi câu hỏi người học.
  - `backend/app/api/v1/tutor.py`: retrieval trước khi build prompt; frame SSE `citations`;
    lưu citation vào message; `_make_source_reader` mở session riêng, scope theo course/user.
  - `backend/app/api/v1/sources.py`: `POST /v1/courses/{id}/sources/search` (CSRF, rate limit,
    `sourceIds` chỉ thu hẹp trong nguồn đã liên kết); ingest-config trả trạng thái embedding/RAG thật.
  - `backend/app/worker/ingest.py`: embed ngay sau ingest (best-effort) + `backfill_embeddings` +
    task `reconcile_embeddings` trên beat.
  - `backend/alembic/versions/0012_p41_rag.py`: `source_chunk_embeddings` (UNIQUE spec, FK CASCADE,
    index), `tutor_messages.citations` (jsonb nullable), index `source_chunks(text_hash)`,
    GIN `to_tsvector('simple', text)` (chỉ PostgreSQL).
  - Frontend: `TutorPanel` hiển thị citation đã verify + nguồn đã truy xuất nhưng **chưa dẫn**
    (style khác, `evidenceSupported=false`); `/sources` hiển thị trạng thái RAG/embedding thật.
  - `backend/evals/rag_dataset.py` (4 tài liệu VI+EN, 16 query có ground truth page; 2 abstain),
    `backend/evals/rag_eval.py`, `backend/evals/rag_benchmark.py`.
  - `docs/specs/20-P41-HYBRID-RAG.md` (quyết định + giới hạn), cập nhật `11-SOURCES-AND-RAG.md`,
    `database-design.md`, `migration-runbook.md`, master plan.
- TESTED (offline, SQLite):
  - `python -m pytest -q` → **426 passed, 24 skipped**. Mới: `test_p41_rag.py` (23),
    `test_p41_tutor_rag.py` (8), `test_p41_migration_contract.py` (9),
    `test_p41_postgres_concurrency.py` (4, skip khi không có URL).
  - Phủ: embedding deterministic/L2/fold dấu; đổi version ⇒ vector cũ không được tái dùng; prompt không còn nói "chưa có nguồn" khi RAG cấp ngữ cảnh thật; provider
    thật thiếu config fail-fast (không fallback); lexical VI có dấu; vector khớp câu không dấu; RRF xếp
    chunk trúng cả hai ranker lên đầu; cross-user/unlinked/non-ready bị loại; query yếu ⇒
    `insufficientEvidence`; citation bịa bị loại; `evidenceSupported=False`; allowlist khớp đúng prompt
    (test hồi quy); SSE frame `citations`; `read_source` ok / no-evidence / unavailable khi RAG tắt;
    thread detail có citation sau reload; API search CSRF/503/scope.
  - `npm run build` → OK; `npx tsc --noEmit` → 0 lỗi.
- TESTED (PostgreSQL throwaway `p41_race_check`, đã drop):
  - `POSTGRES_TEST_URL=…/p41_race_check python -m pytest tests/test_p41_postgres_concurrency.py -q`
    → **4 passed**: FTS `simple` khớp tiếng Việt có dấu; ownership filter ở SQL (link nguồn A vào
    course B vẫn không lộ); 8 worker upsert đồng thời ⇒ đúng 1 row/chunk; vector stale
    (`text_hash` cũ) bị loại.
- TESTED (migration PostgreSQL throwaway `p41_migration_check`, đã drop):
  - `upgrade 0011` → seed user+source → `upgrade head` → `0012_p41_rag (head)`;
    `source_chunk_embeddings` 11 cột, UNIQUE spec, 2 FK CASCADE; GIN `ix_source_chunks_fts_simple`;
    `tutor_messages.citations` jsonb nullable.
  - `downgrade 0011` → GIN index + bảng embeddings + cột biến mất, `users`/`sources` còn **1/1**;
    `upgrade head` lại thành công.
- TESTED (Docker full stack, mock provider, worker Celery thật):
  - Flag mặc định (RAG/Tutor tắt): `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py`
    → **60/60 PASS** (thêm 11p kiểm 503 `RAG_NOT_ENABLED`).
  - Bật `RAG_ENABLED=true TUTOR_ENABLED=true TUTOR_TOOLS_ENABLED=true` → **72/72 PASS**
    (11p provenance đầy đủ, 11q abstain, 12x tutor + tool + stop + quota).
  - Kiểm thủ công qua HTTP thật: upload PDF 2 trang → `ready`, link course, hỏi tutor ⇒ nhận frame
    `citations` với `pageNumber=1`, `sectionAnchor="Chapter 1: Loops"`, `textHash`,
    `validationStatus=locator_verified`, `evidenceSupported=false`; search API trả 2 chunk.
  - Worker log: `embed ready source_id=… chunks=2`; DB dev `20 chunks / 20 embeddings`, một spec duy
    nhất `hashing/hashing-ngram-v1/d256/v1` (không trộn vector).
- TESTED (eval + benchmark: `python -m evals.rag_eval`, `python -m evals.rag_benchmark`):
  - Retrieval: **Recall@6 = 1.000, MRR = 0.964, abstention = 1.000, p50 ≈ 5 ms, p95 ≈ 8 ms**
    (16 query: 7 EN, 9 VI). Theo ngôn ngữ: EN recall 1.0/MRR 1.0; VI recall 1.0/MRR 0.9375.
  - Benchmark scale (SQLite exact scan): 500 chunk → p95 **84 ms**; 2000 → **368 ms**; 8000 →
    **460 ms** (vector ~15.6 MB). Ngân sách 150 ms ⇒ **cần pgvector/ANN khi corpus vượt khoảng
    700 chunk**, không sớm hơn.
- NOT TESTED:
  - **Semantic quality** của embedding thật (chưa cấu hình provider; chưa có key/chi phí được duyệt).
  - **Groundedness / citation precision** (cần LLM judge hoặc nhãn người); hiện chỉ có retrieval
    metrics + structural citation validity.
  - Dataset eval **16 query < 30** theo acceptance plan ⇒ chưa đủ quy mô; ghi BLOCKED ở plan.
  - Corpus lớn thật (>2000 chunk) trên PostgreSQL; HNSW/reranker (chưa triển khai, chưa benchmark).
  - Mở đúng trang PDF trong UI (chỉ hiển thị số trang + section anchor).
  - Multi-turn retrieval follow-up (query hiện tại = câu hỏi + block digest).
  - OCR/PDF scan (P4.3), web/arXiv (P4.2).
- BLOCKED: **không** blocked code. Bị chặn bởi quyết định/chi phí: chọn embedding model thật + key +
  ngân sách; mở rộng eval ≥30 query có nhãn người; quyết định UI mở PDF.
- Security: mọi truy vấn retrieval scope owner/course ở SQL (test cả PostgreSQL với dữ liệu xấu);
  citation chỉ từ allowlist của request; `evidenceSupported` luôn False; prompt tài liệu nằm trong
  delimiter untrusted; log không chứa nội dung/câu hỏi; API search có CSRF + rate limit; embedding key
  chỉ server-side, không trả ra response.
- Regressions: 0. pytest 385 → **426 passed** (+41); E2E 60 → **72/72** khi bật RAG/Tutor.
- Known limitations:
  - `hashing` có collision và không hiểu ngữ nghĩa; ngưỡng `RAG_MIN_LEXICAL_SCORE` /
    `RAG_VECTOR_ONLY_MIN_SIMILARITY` hiệu chỉnh trên 16 query — **phải hiệu chỉnh lại** khi đổi
    corpus/model.
  - `groundingAvailable` vẫn `false`: P4.1 chỉ mở retrieval trong tutor, không đổi grounding của
    lesson generation.
  - Exact vector scan có trần; >~700 chunk cần pgvector (số đo ở trên).
- PHASE GATE: **GATE-PARTIAL** — code + test chạy thật đầy đủ cho baseline offline, nhưng acceptance
  đầy đủ (≥30 query, groundedness) chưa đạt. Không tuyên bố chất lượng semantic.
- NEXT: P4.2 (web/arXiv có SSRF guard) **hoặc** P5.0 (Learner Profile/FSRS) nếu ưu tiên mastery;
  trước P4.2 cần quyết định corpus/eval scale và (nếu dùng model thật) key + ngân sách.

## 2026-10-31 — P4.0 PDF text ingestion + source provenance

- Base commit: `9f5b5bf` (branch `main`, working tree)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Storage thật: MinIO (S3-compatible)** theo yêu cầu, không fallback ghi đĩa. Object key do server
    sinh ngẫu nhiên `sources/<source_id>/<uuid4>`; bucket private; upload/đọc chỉ qua service sau auth.
    `SOURCE_STORAGE_BACKEND` rỗng ⇒ upload trả `503 STORAGE_NOT_CONFIGURED`. Backend `memory` chỉ
    dành cho pytest/dev và bị từ chối khi `ENV=production`.
  - **Không tin client**: kiểm tra magic `%PDF-`, trần byte (stream 1 MB/chunk, vượt ⇒ 413 trước khi
    parse), trần số trang, PDF mã hoá/corrupt/không trang ⇒ mã lỗi ổn định. MIME ghi vào storage là
    `application/pdf` sau khi xác minh, không lấy Content-Type client.
  - **Chỉ trích text, không OCR.** PDF scan ⇒ `status=no_text` + `errorCode=NO_EXTRACTABLE_TEXT`
    (không bịa nội dung, không báo `ready`).
  - **Chunking theo trang, không overlap**, giữ `page_number`, `char_start/char_end` trong text của
    TRANG (không phải byte PDF), `section_anchor` (heading gần nhất) và `text_hash`. Chunk quá ngắn
    được gộp vào chunk trước **cùng trang**; block quá dài cắt theo dòng/câu.
  - **Idempotent** theo `UNIQUE(source_id, content_hash, pipeline_version)`; ingest lại thay chunk
    theo `document_id` trong một transaction. Upload trùng bytes trả document cũ, không chạy lại job.
  - **Worker P1.2-style**: claim nguyên tử + lease/heartbeat + bounded attempts; Celery task
    `app.worker.ingest.run_ingest_task`; reconciler `reconcile_ingest` trên beat (outbox + lease hết hạn).
  - **Trung thực trạng thái**: có chunk chỉ đổi citation `unavailable → unverified` và làm
    `evidence` criterion của evaluator có dữ liệu; **không** tạo `locator_verified`/`evidence_supported`,
    không làm bài học `source_grounded`, `groundingAvailable` vẫn `false` cho tới P4.1.
  - **Ownership**: upload/xoá chỉ trên nguồn **private của chính user** (`get_owned_source`); nguồn
    public dùng chung và nguồn người khác ⇒ 404. Xoá nguồn dọn document/chunk/course link/lesson
    citation + object storage (best-effort).
  - **Log không chứa nội dung**: chỉ `document_id`, `source_id`, bytes, pages, chunks, error code.
- IMPLEMENTED:
  - `backend/app/models/models.py` + `models/__init__.py`: `SourceDocumentStatus` (queued/extracting/
    ready/no_text/failed), `SourceDocument`, `SourceChunk` (unique/index/FK cascade).
  - `backend/alembic/versions/0011_p40_source_ingest.py`: 2 bảng + enum + index, expand-only,
    downgrade đối xứng (đã chạy thật trên PostgreSQL throwaway).
  - `backend/app/services/storage.py`: interface `put/get/delete/delete_prefix`, `S3Storage` (minio SDK),
    `InMemoryStorage` cho test, `sanitize_filename`, `build_object_key`.
  - `backend/app/services/ingest.py`: `check_limits`, `extract_pages`, `chunk_pages`,
    `register_document`, `claim_document`/`renew_lease`, `finish_ready`/`finish_no_text`/
    `fail_document`, `get_owned_document`, `source_has_content`, `delete_source_documents`,
    `wrap_untrusted` + delimiter `<<<NGUON_BAT_DAU>>>`.
  - `backend/app/worker/ingest.py`: task + `dispatch_document` (broker hoặc inline blocking) +
    `recover_stuck_documents`; `celery_app.include` + beat schedule.
  - `backend/app/api/v1/sources.py`: `GET /v1/sources/ingest-config`,
    `POST /v1/sources/{id}/document` (202, multipart, CSRF, rate limit),
    `GET /v1/sources/{id}/documents`, `GET /v1/sources/{id}/documents/{docId}`,
    `DELETE /v1/sources/{id}/documents/{docId}`, `DELETE /v1/sources/{id}`;
    `list_course_sources` trả `contentIngested` thật.
  - `backend/app/schemas/schemas.py`: `SourceDocumentOut`, `SourceDocumentListOut`, `SourceIngestConfigOut`.
  - `backend/app/services/source_service.py`: `get_owned_source` (private + owner).
  - `backend/app/core/config.py`: `SOURCE_*` (ingest limits, chunking, pipeline version, lease, storage)
    + `source_storage_configured` (từ chối `memory` ở production).
  - `docker-compose.yml`: service `minio` (+ healthcheck wget, volume `miniodata`), tham số `SOURCE_*`
    cho backend/worker/beat, endpoint nội bộ `minio:9000`.
  - `backend/requirements.txt`: `pypdf`, `python-multipart`, `minio`.
  - Frontend: `src/app/sources/page.tsx` (tạo nguồn, upload PDF, poll trạng thái, xoá document/nguồn,
    lỗi theo mã), `src/lib/api.ts` (types + `uploadSourceDocument` multipart + config), link từ trang chủ.
  - `backend/e2e_acceptance.py`: +5 check P4.0 (config không lộ secret, upload→ready, upload trùng,
    provenance/preview, MIME sai bị từ chối, scan→no_text, `contentIngested` trung thực).
- TESTED (offline, SQLite):
  - `python -m pytest -q` → **385 passed, 20 skipped** (34.5s). Mới: `test_p40_ingest.py` (28),
    `test_p40_chunker.py` (2), `test_p40_honesty.py` (2), `test_p40_migration_contract.py` (9),
    `test_p40_postgres_concurrency.py` (3, skip khi không có URL).
  - `test_p40_ingest.py` phủ: happy path provenance, offset khớp đúng substring trang, không overlap,
    contentHash ghi nhận + vẫn `unverified`, idempotent upload/re-ingest, nhiều document khác nội dung,
    `no_text`, MIME sai/rỗng/corrupt/oversize/too-many-pages, CSRF, source không tồn tại,
    owner A/B isolation (upload/read/delete), document thuộc nguồn khác, xoá document/source + storage,
    nguồn public không upload được, prompt-injection ở lại khối untrusted, preview ≤200 ký tự,
    `contentIngested` thật, config không lộ secret/endpoint/bucket, storage chưa cấu hình ⇒ 503,
    lỗi storage tạm thời ⇒ `queued` + retry chạy lại được, upload lại sau `failed` còn lượt ⇒ retry,
    upload lại khi đã cạn lượt ⇒ vẫn `failed` (không tự "chữa" trạng thái).
  - `npm run build` → OK (10 routes, thêm `/sources`); `npx tsc --noEmit` → 0 lỗi.
- TESTED (PostgreSQL throwaway `p40_race_check`, đã drop):
  - `POSTGRES_TEST_URL=…/p40_race_check python -m pytest tests/test_p40_postgres_concurrency.py -q`
    → **3 passed**: 8 upload đồng thời cùng bytes ⇒ 1 document; 6 worker claim đồng thời ⇒ 1 thắng,
    `attempts_count=1`, status `extracting`; cross-user lookup ⇒ `SOURCE_DOCUMENT_NOT_FOUND`.
- TESTED (migration PostgreSQL throwaway `p40_migration_check`, đã drop):
  - `alembic upgrade 0010_p31_tutor_tools` → seed user + source → `upgrade head` → exit 0;
    `alembic_version=0011_p40_source_ingest`, `source_documents` 21 cột, user/source cũ còn nguyên,
    metadata source cũ đọc đúng.
  - `alembic downgrade 0010_p31_tutor_tools` → exit 0; 2 bảng P4.0 + enum biến mất, `sources`/`users`
    vẫn còn; `upgrade head` lại thành công.
- TESTED (Docker full stack + MinIO thật + Celery worker):
  - MinIO container `healthy` (healthcheck `wget .../minio/health/live`); backend roundtrip
    `put/get/delete` qua `S3Storage` OK; bucket `sopiskill-sources` tự tạo.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **59/59 PASS** (mock provider,
    worker Celery thật): upload text PDF → `ready` (2 trang, 2 chunk), upload trùng không nhân bản,
    document detail có provenance/preview, MIME sai 422, scan → `no_text`, `contentIngested=true`
    nhưng citation vẫn `unverified`/`unavailable` và `groundingAvailable=false`.
  - Worker log: `ingest ready document_id=… pages=2 chunks=2`, `ingest no_text`, 0 Traceback.
- NOT TESTED:
  - Chất lượng/độ phủ trích text trên PDF thật phức tạp (bảng, cột, công thức, font CJK/ToUnicode
    lỗi) — chỉ test PDF fixture do script sinh.
  - Malware scan/quarantine thật (không triển khai); zip-bomb/PDF-bomb ngoài trần byte/page.
  - S3/MinIO production: HTTPS/TLS, bucket policy, lifecycle, credential rotation; retention/deletion
    theo chính sách pháp lý.
  - Real provider + nguồn đã ingest: chưa nối RAG (P4.1) nên chưa có câu trả lời grounded.
  - UI `/sources` mới build + typecheck, **chưa** có E2E browser (Playwright) — kiểm qua HTTP API.
  - **Lưu ý môi trường:** `docker pull minio/minio:latest` bị registry từ chối trong lần chạy này; đã
    kiểm chứng bằng image MinIO có sẵn trên máy và tag lại `minio/minio:latest`. Trên máy khác cần
    `docker compose pull minio` thành công trước khi `up`.
- BLOCKED: không cho P4.0. (Registry MinIO ở môi trường hiện tại từ chối pull — đã dùng image sẵn có;
  không ảnh hưởng code, nhưng máy mới cần pull được.) P4.1 (embedding/pgvector/retrieval/certified
  citations) chưa bắt đầu.
- Database: **có migration** `0011_p40_source_ingest` (expand-only, upgrade/downgrade đã chạy thật).
- Security: upload chỉ nguồn private của chính user; object key ngẫu nhiên, không lộ trong API; magic
  byte + size + page limits; không shell/network trong parser; log không chứa text; CSRF + rate limit;
  scan không bị đánh dấu `ready`; citation không tự "verified" chỉ vì có chunk.
- Regressions: 0. pytest 380 → **385 passed** (thêm 44 test P4.0); E2E 47 → **59/59**; build/tsc OK;
  generation/quiz/XP/progress/tutor flow không đổi (mock regression xanh).
- Known limitations:
  - `locator_verified`/`evidence_supported` **chưa từng** được tạo ra — cần P4.1.
  - `groundingAvailable` vẫn `false` dù đã ingest; `excerpt_provider` cố ý chưa nối.
  - Parser pypdf bỏ qua text trong vector/ảnh; PDF scan trả `no_text` (OCR là P4.3).
  - Chưa có UI mở PDF tới đúng trang (citation UI thật thuộc P4.1).
- PHASE GATE: **PASS cho P4.0 (PDF text ingestion + provenance)** — mọi mục con có bằng chứng chạy
  thật; các giới hạn ở trên được ghi rõ, không suy diễn thành năng lực đã có.
- NEXT: **P4.1** — embedding model/dimension gate, pgvector, lexical + vector retrieval có filter
  owner, RRF, citation validator, `read_source` mở, eval Recall@k/citation precision.

## 2026-10-31 — P3.1 (lát B) Tutor tool allowlist + audit

- Base commit: `b92c414` (branch `main`, working tree)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Server-side deterministic tools, không native `tool_calls`.** Model trả JSON `{tool, args}`
    qua hook `plan_tutor_tool`; server parse → validate → execute. Mock, adapter OpenAI-compatible
    và provider tương lai dùng chung một contract, và **server là bên duy nhất thực thi** — model
    không bao giờ tự chạy tool.
  - **Allowlist là hằng số, không cấu hình runtime.** `read_lesson`, `explain_deeper` khả dụng;
    `read_source` được allowlist nhưng trả `TUTOR_TOOL_NOT_AVAILABLE` tới khi P4.1 có chunk
    ownership/provenance. Từ chối thật thay vì bịa trích dẫn.
  - **Tool chỉ đọc public blocks.** Executor nhận `prepared.blocks` (đã qua `public_blocks`) nên
    không có `answerIndex`/`answer`/`acceptedAnswers`/`pairs`; test kiểm cả prompt gửi provider.
  - **Bounded loop, không runaway.** `TUTOR_TOOL_MAX_CALLS=2`, planner timeout 3s, dừng sau kết quả
    đầu tiên. Planner lỗi/không hỗ trợ/trả rác ⇒ coi như không dùng tool, lượt hỏi vẫn trả lời.
  - **Kết quả tool là dữ liệu không tin cậy** (delimiter `<<<TOOL_BAT_DAU>>>`) — chống prompt
    injection từ nội dung bài; kết quả cắt theo `TUTOR_TOOL_MAX_RESULT_CHARS`.
  - **Audit metadata-only.** Bảng `tutor_tool_calls` lưu name/ok/duration/summary(server dựng)/
    error_code. Không lưu nội dung tool, args thô của model hay prompt.
  - **Mặc định TẮT** (`TUTOR_TOOLS_ENABLED=false`) để hành vi P3.1 lát A không đổi.
- IMPLEMENTED:
  - `backend/app/services/tutor_tools.py` (mới): allowlist `TOOLS`, Pydantic args `extra=forbid`,
    `parse_tool_request`, `validate_request` (biên block), `execute` (read-only), `audit_summary`,
    `TOOL_PLANNER_SYSTEM`, mã lỗi `TUTOR_TOOL_NOT_ALLOWED` / `TUTOR_TOOL_INVALID_ARGS` /
    `TUTOR_TOOL_NOT_AVAILABLE` / `TUTOR_TOOL_FAILED`.
  - `backend/app/services/tutor_context.py`: `build_tool_results_section` (dữ liệu không tin cậy).
  - `backend/app/services/tutor_service.py`: `record_tool_call`, `list_tool_calls`.
  - `backend/app/models/models.py` + `app/models/__init__.py`: `TutorToolCall` (+ index/FK cascade).
  - `backend/alembic/versions/0010_p31_tutor_tools.py` (mới): bảng `tutor_tool_calls` + 4 index,
    expand-only, downgrade đối xứng.
  - `backend/app/providers/base.py`: hook `plan_tutor_tool` (mặc định raise `ProviderConfigError`).
  - `backend/app/providers/mock_provider.py`: planner deterministic theo keyword (không phải AI).
  - `backend/app/providers/openai_compatible_provider.py`: `plan_tutor_tool` qua `request_json`;
    lỗi provider ⇒ `{tool: None}` để lượt hỏi vẫn trả lời.
  - `backend/app/api/v1/tutor.py`: `_plan_tools` (bounded loop), `_persist_tool_audit` (ghi trước
    frame đầu), frame SSE `tool`, đưa kết quả tool vào system prompt sau dấu phân cách.
  - `backend/app/core/config.py` + `.env.example` + `docker-compose.yml` (3 service):
    `TUTOR_TOOLS_ENABLED`, `TUTOR_TOOL_MAX_CALLS`, `TUTOR_TOOL_TIMEOUT_SECONDS`,
    `TUTOR_TOOL_MAX_RESULT_CHARS`.
  - Frontend: `lib/api.ts` thêm event `tool` + field types; `TutorPanel.tsx` khung
    "Công cụ trợ giảng đã dùng" (aria-label, ok/bị từ chối + mã), reset mỗi lượt; CSS
    `.tutor-tool-notes`.
  - `backend/e2e_acceptance.py`: +2 check `12k` (tool frame + turn done, hoặc flag tắt không frame),
    `12l` (stream không lộ answer key) + helper `public_answer_is_leaked_text`.
- TESTED (offline, SQLite in-memory):
  - `cd backend && python -m pytest -q` → **344 passed, 17 skipped** (31.72s; trước 322/16).
    Mới: `tests/test_p31_tutor_tools.py` (**17 test**),
    `tests/test_p31_tutor_tools_migration_contract.py` (**5 test**).
  - Tool ngoài allowlist bị chặn trước execute và vẫn audit `TUTOR_TOOL_NOT_ALLOWED`; frame không
    chứa args của tool bị chặn; lượt hỏi vẫn `done`.
  - Args sai schema (`extra`, thiếu `blockIndex`, âm) và `blockIndex` ngoài biên ⇒
    `TUTOR_TOOL_INVALID_ARGS`; planner trả rác/`args` không phải dict ⇒ không tool nào chạy.
  - Planner raise `ProviderError` hoặc provider không hỗ trợ tool ⇒ không có frame `tool`, lượt hỏi
    vẫn trả lời đầy đủ.
  - `read_source` ⇒ `TUTOR_TOOL_NOT_AVAILABLE` (không bịa nguồn).
  - Prompt gửi provider chứa kết quả `read_lesson` nhưng **không** chứa `answerIndex`/
    `acceptedAnswers`/`pairs`/`"answer"`.
  - Tool call không tạo message hay usage event thừa; audit không có cột/không chứa nội dung bài.
  - `cd frontend && npx tsc --noEmit` → 0 lỗi; `npm run build` → OK (9 routes).
- TESTED (PostgreSQL throwaway `p31b_migration_check`):
  - `alembic upgrade head` → `0010_p31_tutor_tools (head)`, 19 bảng; `tutor_tool_calls` 10 cột,
    FK `users`/`courses`/`tutor_messages` (`ON DELETE CASCADE`), 4 index.
  - `alembic downgrade 0009_p31_tutor_controls` → 18 bảng, bảng audit biến mất;
    `tutor_messages.content/status` giữ nguyên; `upgrade head` lại OK.
- TESTED (PostgreSQL race, throwaway `p31b_race_check`):
  - `POSTGRES_TEST_URL=…/p31b_race_check python -m pytest tests/test_p31_tutor_postgres_concurrency.py -q`
    → **5 passed** (thêm: 6 audit ghi song song đều được lưu, đúng `message_id`).
- TESTED (Docker full stack + E2E, mock provider):
  - Backup trước upgrade: `backup_pre_p31b_20261031_142709.sql` (trong container db).
  - `docker compose up -d --build backend worker beat` → DB dev `ailp` ở `0010_p31_tutor_tools`;
    health 200.
  - `TUTOR_ENABLED=true TUTOR_TOOLS_ENABLED=true` → **63/63 PASS** (`12k` tool=explain_deeper
    status=ok; `12l` không lộ answer key trong 15 435 byte stream).
  - `TUTOR_ENABLED=true` (tools off) → **62/62 PASS** (`12k` xác nhận không có frame `tool`).
  - Mặc định (tutor off) → **52/52 PASS**.
  - Audit thật trong dev DB: 1 row `explain_deeper|true||64` (summary 64 ký tự, không nội dung bài).
- NOT TESTED:
  - **Chất lượng tool với model thật**: mock planner là rule keyword; chưa chạy provider thật
    (không có quyền/ngân sách) ⇒ khả năng model chọn đúng tool là **UNKNOWN**.
  - Native tool-calling: **không triển khai** (quyết định DEC-P31-B1) nên không có gì để test.
  - Browser E2E (Playwright) cho khung tool notes.
  - `read_source` (chờ P4.1).
- BLOCKED: none cho lát B. `read_source` bị chặn có chủ ý bởi P4.1.
- Database: **có migration** `0010_p31_tutor_tools` (expand-only; upgrade/downgrade/legacy-row đã
  kiểm chứng trên DB throwaway; DB dev đã backup + upgrade).
- Security: allowlist cố định + validate trước execute; biên block theo public projection; tool
  không truy cập mạng/DB/ghi dữ liệu; kết quả tool là dữ liệu không tin cậy; audit không chứa
  nội dung; frame `tool` không chứa raw args; flag mặc định tắt.
- Regressions: 0. pytest 322 → **344 passed / 17 skipped**; E2E 63/63 (tutor+tools), 62/62 (tutor),
  52/52 (off); tsc 0 lỗi; build OK.
- Known limitations:
  - Planner là một lời gọi LLM phụ ⇒ với provider thật, mỗi lượt có thể tốn thêm 1 request. Token
    của planner nằm trong cùng `UsageCollector` nên được tính vào `TUTOR_TOKENS_PER_DAY` (chưa kiểm
    với provider thật, vì mock không báo usage).
  - Dừng sau 1 tool call: chưa hỗ trợ chuỗi nhiều tool (cố ý, tránh vòng lặp).
  - Summary audit chỉ mô tả vị trí/loại, không phải bản ghi tái lập được.
- PHASE GATE: **P3.1 = PASS cho phạm vi đã định nghĩa** (lát A + lát B, mock planner).
  Chất lượng tool với model thật và `read_source` vẫn **NOT TESTED / BLOCKED by P4.1**.
- NEXT: **P4.0** PDF ingestion (mở đường cho `read_source` + citation thật).

## 2026-10-31 — P3.1 (lát A) Tutor controls: stop, allowance, stale recovery, replay semantics

- Base commit: `117e784` (branch `main`, working tree)
- New commit/branch: **NOT COMMITTED** (working tree)
- Phạm vi: **lát A** của P3.1. Lát B (tool allowlist `read_lesson`/`explain_deeper` + audit
  `tool_calls`) **chưa làm** — cần mở rộng provider contract, ghi rõ NOT IMPLEMENTED.
- Scope & decisions:
  - **Stop là best-effort có kiểm soát, không phải "cancel là xong".** Endpoint chỉ ghi cờ
    `cancel_requested_at`; task stream còn sống mới ghi trạng thái cuối + nội dung đã nhận. Stop trên
    message đã xong trả trạng thái thật (`completed`), không giả vờ đã dừng. Response luôn có
    `providerStopGuaranteed=false` vì **không thể hoàn chi phí/token provider đã sinh**.
  - **Kiểm cờ theo thời gian, không chỉ khi queue rỗng.** Đây là lỗi dễ mắc: nếu chỉ kiểm trong nhánh
    `asyncio.TimeoutError`, provider trả token liên tục thì vòng lặp không bao giờ vào nhánh đó ⇒ stop
    vô hiệu. Test `test_running_stream_detects_cancel_flag_in_frame_stream` chứng minh stop hoạt động
    với provider "endless".
  - **Allowance đếm từ DB, không RAM.** Lượt = số user message trong 24h; token = tổng
    `prompt_tokens + completion_tokens` của `tutor_usage_events`. Provider không báo token ⇒ token = 0
    và API trả `tokensKnown=false`: trần token **không** bảo vệ được chi phí trong trường hợp đó.
  - **Replay: chốt explicit restart.** Giữ `id = streamId:seq` nhưng **không** hỗ trợ `Last-Event-ID`
    (không có event log bền vững). Mất mạng ⇒ tải lịch sử; `replaySupported=false` giữ nguyên.
  - **Stale recovery thay vì treo `running` vĩnh viễn.** Server restart làm stream chết nhưng row vẫn
    `running` ⇒ user bị 409 mãi. Reap thành `failed/TUTOR_STALE` khi bắt đầu lượt mới hoặc gọi usage.
- IMPLEMENTED:
  - `backend/app/models/models.py`: `TutorMessage.cancel_requested_at` (nullable),
    `Index("ix_tutor_messages_status")`, model mới `TutorUsageEvent` (metadata-only).
  - `backend/alembic/versions/0009_p31_tutor_controls.py` (mới): cột nullable + 1 index + bảng usage
    (+2 index), expand-only, downgrade đối xứng.
  - `backend/app/services/tutor_service.py`: `quota_state`, `_used_today`, token quota,
    `count_running_streams`, `_check_concurrency`, `reap_stale_messages`, `request_cancel`,
    `is_cancel_requested`, `record_usage`; `_error` nhận `quota` có cấu trúc; mã lỗi mới
    `TUTOR_TOKEN_LIMIT_REACHED`, `TUTOR_CONCURRENCY_LIMIT`, `TUTOR_STALE`, `TUTOR_STOP_NOT_FOUND`.
  - `backend/app/api/v1/tutor.py`: `POST .../messages/{messageId}/stop`, `GET .../tutor/usage`,
    poll cờ stop theo thời gian, frame SSE `cancelled`, usage trong frame `done`
    (`promptTokens/completionTokens/known`), đợi producer đóng trước khi báo `done` để không mất usage,
    persist `tutor_usage_events` bằng task tách rời sau stream.
  - `backend/app/core/config.py` + `.env.example` + `docker-compose.yml` (3 service):
    `TUTOR_TOKENS_PER_DAY`, `TUTOR_MAX_CONCURRENT_STREAMS`, `TUTOR_STALE_STREAM_SECONDS`,
    `TUTOR_CANCEL_POLL_SECONDS`.
  - `backend/app/schemas/schemas.py`: `TutorUsageOut`, `TutorQuota*`, `TutorStopOut`.
  - Frontend: `lib/api.ts` (`fetchTutorUsage`, `stopTutorMessage`, `onMessageId`, event `cancelled`,
    type usage trong `done`), `TutorPanel.tsx` (Dừng gọi server trước rồi abort, hiển thị
    remaining/limits + `tokensKnown`, disable gửi khi hết quota, `aria` giữ nguyên),
    `globals.css` (`.tutor-quota`).
  - `backend/e2e_acceptance.py`: +3 check `12h` (usage có cấu trúc), `12i` (stop message đã xong trả
    trạng thái thật), `12j` (stop message lạ 404).
- TESTED (offline, SQLite in-memory):
  - `cd backend && python -m pytest -q` → **322 passed, 16 skipped** (27.47s; trước 306/12).
    Mới: `tests/test_p31_tutor_controls.py` (**11 test**), `tests/test_p31_tutor_migration_contract.py`
    (**5 test**).
  - Stop giữa stream với provider phát token liên tục ⇒ frame `cancelled`, producer bị hủy
    (`produced < 9999`), DB `cancelled` + `error_code=TUTOR_CANCELLED`, phần đã nhận giữ nguyên.
  - Stop idempotent (2 lần gọi không lỗi), stop message lạ 404, cross-user 404, thiếu CSRF 403,
    stop message đã completed trả `completed` + không đổi nội dung.
  - Quota lượt/token chặn **trước** khi tạo message (0 message, không gọi provider); 429 kèm
    `detail.quota.used/remaining`; concurrency limit chặn stream thứ hai; stale reap mở khóa user.
  - `cd frontend && npx tsc --noEmit` → 0 lỗi; `npm run build` → OK (9 routes, lesson 5.8 kB).
- TESTED (PostgreSQL throwaway `p31_tutor_migration_check`):
  - `alembic upgrade head` → exit 0 → `0009_p31_tutor_controls (head)`, 18 bảng;
    `tutor_usage_events` 11 cột, FK users/courses/tutor_messages, index `(user_id, created_at)`;
    `cancel_requested_at` nullable; `ix_tutor_messages_status` tồn tại.
  - `alembic downgrade 0008_p30_tutor_core` → exit 0 → 17 bảng, bảng usage + cột + index biến mất;
    `alembic upgrade head` lại OK.
  - Seed legacy ở 0008 (lesson `content_version=3`, thread + message `completed`) → upgrade head →
    lesson giữ nguyên, message giữ `status=completed`/`content='cũ'`/`cancel_requested_at` NULL
    ⇒ **không mất dữ liệu**.
- TESTED (PostgreSQL race, throwaway `p31_tutor_race_check`):
  - `POSTGRES_TEST_URL=…/p31_tutor_race_check python -m pytest tests/test_p31_tutor_postgres_concurrency.py -q`
    → **4 passed**: 8 stop song song idempotent; stop sau terminal không ghi đè; 5 usage event song
    song cộng đúng 75 token; stale reap sau khi mark running.
- TESTED (Docker full stack + E2E, mock provider):
  - Backup trước khi upgrade: `backup_pre_p31_20261031_140156.sql` (trong container db).
  - `docker compose up -d --build backend worker beat` → backend tự `alembic upgrade head`; DB dev
    `ailp` ở `0009_p31_tutor_controls`; health 200.
  - Flag **TẮT**: `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **52/52 PASS**.
  - Flag **BẬT** (`TUTOR_ENABLED=true docker compose up -d backend`) → **61/61 PASS** (12h usage,
    12i stop completed, 12j stop 404 đều pass).
  - Trả mặc định (`docker compose up -d backend`) → E2E lại **52/52**.
- NOT TESTED:
  - **Real provider stop**: dừng vòng đọc SSE của server đã test, nhưng chưa kiểm với provider thật
    (không có quyền/ngân sách) ⇒ hành vi tính phí/độ trễ dừng upstream là **UNKNOWN**.
  - `tokensKnown=true` với usage thật từ provider: trần token mới test bằng seed event + record_usage
    trực tiếp, chưa test end-to-end qua adapter OpenAI-compatible thật.
  - Browser E2E cho nút Dừng mới (Playwright): build+typecheck OK, chưa chạy trình duyệt.
  - Tool allowlist/audit `tool_calls` (P3.1 lát B) — **NOT IMPLEMENTED**.
- BLOCKED: none cho lát A. Lát B (tools) cần chốt schema tool-call (server-side deterministic vs
  native tool API) trước khi code.
- Database: **có migration** `0009_p31_tutor_controls` (expand-only; upgrade/downgrade/legacy-row đã
  kiểm chứng trên DB throwaway; DB dev đã backup + upgrade).
- Security: stop owner-scoped 404 + CSRF; quota chặn trước provider; usage event không chứa nội dung;
  log không chứa prompt/key; stale reap không tự đánh dấu `completed`; `cancelled` không xóa nội dung.
- Regressions: 0. pytest 306 → **322 passed / 16 skipped**; E2E 52/52 (off) và 61/61 (on); build OK.
- Known limitations:
  - Stop không dừng được request đã gửi tới provider (chỉ dừng đọc stream) ⇒ token đã sinh vẫn tính phí.
  - Trần token vô hiệu nếu provider không báo usage (`tokensKnown=false`).
  - Rate limit vẫn in-memory per-process, chưa phân tán (P6).
  - Không có `Last-Event-ID`/resume byte-by-byte (quyết định tường minh).
- PHASE GATE: **P3.1 lát A = PASS** (cancel/allowance/stale/replay-semantics/UI quota có bằng chứng);
  **lát B (tools) = NOT STARTED**, không được coi P3.1 là hoàn tất trọn vẹn.
- NEXT: **P3.1 lát B** (tool allowlist + audit) hoặc **P4.0** PDF ingestion.

## 2026-10-31 — P3.0 AI Tutor Core (SSE + lesson grounding)
- Base commit: `50e47c9` (branch `main`, working tree)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Tutor ground trên PUBLIC blocks, không phải `lessons.content`**: system prompt chỉ chứa bản
    public (đã loại `answerIndex`/`answer`/`acceptedAnswers`/`pairs`) ⇒ tutor không thể vô tình đọc
    đáp án quiz đang làm. Đây là quyết định bảo mật, không chỉ là chi tiết hiển thị.
  - **Client chỉ gửi VỊ TRÍ** (`lessonId` + `blockIndex`); server resolve lại course → lesson →
    block và kiểm biên. Request có `systemPrompt`/`lessonContent`/`sources`/`ownerId` bị **422**
    (`extra=forbid`), không âm thầm bỏ qua.
  - **Idempotency ở tầng DB, không phải RAM**: `UNIQUE(course_id, clientMessageId, role)` +
    `SELECT … FOR UPDATE` per-user. Retry khi đã xong ⇒ **replay** nội dung đã lưu và **không** gọi
    provider; retry khi đang chạy ⇒ `409 MESSAGE_IN_PROGRESS` (không multiplex stream ở P3.0).
  - **Không hứa resume**: chưa có event log bền vững nên `replaySupported=false` trong response và
    UI nói rõ "tải lại lịch sử" thay vì giả vờ khôi phục từng byte. `id` frame = `streamId:seq`
    (đơn điệu), để P3.1 có thể thêm `Last-Event-ID` nếu thật sự lưu log.
  - **Trạng thái trung thực**: `pending → running → completed | failed | cancelled`. Client ngắt
    stream ⇒ server ghi `cancelled` + giữ phần đã nhận, không đánh dấu `completed`, không treo
    `running`; mọi lỗi provider thành SSE `error` có mã (không lộ exception).
  - **Không bịa citation**: P3.0 chưa ingest nguồn nên prompt dặn rõ chưa có đoạn nguồn kiểm chứng;
    tên nguồn đã liên kết chỉ để định hướng, cấm trích URL/số trang.
  - **Mặc định TẮT** (`TUTOR_ENABLED=false`) để bảo toàn hành vi cũ; flag tắt ⇒
    `503 TUTOR_DISABLED`.
- IMPLEMENTED:
  - `backend/app/models/models.py`: `TutorMessageRole`, `TutorMessageStatus`, `TutorThread`,
    `TutorMessage` (denormalized `course_id` + `position` để UNIQUE/ordering ổn định).
  - `backend/alembic/versions/0008_p30_tutor_core.py` (mới): 2 bảng + 2 enum + 4 index +
    UNIQUE(course_id, client_message_id, role); expand-only, downgrade đối xứng.
  - `backend/app/services/tutor_service.py` (mới): resolve lesson theo owner+course, kiểm
    blockIndex, lock per-user, idempotent prepare, history bounded, finalize/cancel.
  - `backend/app/services/tutor_context.py` (mới): system prompt từ public blocks + block hiện tại
    + đoạn giảng lân cận (có trần ký tự) + danh sách **tên** nguồn; history builder.
  - `backend/app/services/sse.py` (mới): frame/headers chuẩn (data 1 dòng, no-store,
    `X-Accel-Buffering: no`), `seq_id`.
  - `backend/app/api/v1/tutor.py` (mới): POST stream + GET threads/thread detail; CSRF, rate limit
    (30/phút + 6/10s), quota ngày, header `X-Tutor-Thread-Id`/`X-Tutor-Message-Id`.
  - `backend/app/providers/base.py`: `stream_tutor_reply` (mặc định từ chối ⇒ không giả streaming).
  - `backend/app/providers/mock_provider.py`: stream deterministic, ghi rõ là MOCK.
  - `backend/app/providers/openai_compatible_provider.py`: stream SSE thật (`stream=true`,
    `include_usage`), timeout/429/5xx/4xx → taxonomy, usage ghi cả khi stream bị ngắt.
  - `backend/app/schemas/schemas.py`: `TutorContextRef`, `TutorMessageRequest` (extra=forbid),
    `TutorMessageOut`, `TutorThread*Out`; `LessonOut.courseId` (nullable, backward-compatible).
  - `backend/app/core/config.py` + `.env.example` + `docker-compose.yml`: 8 cấu hình tutor.
  - Frontend: `lib/api.ts` (`streamTutorMessage` parser SSE thật, `AbortSignal`),
    `lesson/[lessonId]/TutorPanel.tsx` (stream, stop, thread switch, `role=log`/`aria-live`,
    Ctrl+Enter, hiển thị lỗi có mã), lesson page chọn block hiện tại; CSS mới.
  - `backend/e2e_acceptance.py`: +6 check (12, 12b–12g) chạy cả hai chế độ flag.
- TESTED (offline, SQLite in-memory):
  - `cd backend && python -m pytest -q` → **306 passed, 12 skipped** (22.84s; trước 270/10).
    Mới: `tests/test_p30_tutor.py` (**21 test**: SSE full turn + reload, seq đơn điệu, event id,
    accumulate history trong cùng thread, duplicate replay không gọi service lần 2, 409 khi đang
    chạy, cross-user 404, lesson khác course 404, blockIndex ngoài biên 422, chặn `systemPrompt`,
    CSRF 403/401, flag tắt 503, quota ngày 429, provider timeout ⇒ SSE error + persist failed,
    provider không hỗ trợ streaming ⇒ error sạch, prompt injection chỉ là user data, thread khác
    lesson 422, public blocks không có answer key, hủy generator ⇒ `cancelled` giữ phần đã nhận), `tests/test_p30_tutor_stream_provider.py`
    (**11 test**: yield chỉ text mới, usage/finish_reason, keep-alive/empty delta, chunk hỏng,
    4 mã HTTP, timeout, truncate input, log không lộ key/prompt),
    `tests/test_p30_tutor_migration_contract.py` (**4 test**).
  - `cd frontend && npx tsc --noEmit` → 0 lỗi; `npm run build` → OK (9 routes, lesson 5.2 kB).
- TESTED (PostgreSQL throwaway `p30_tutor_migration_check`):
  - `alembic upgrade head` → exit 0 → `0008_p30_tutor_core (head)`, 17 bảng; `tutor_messages` có
    `position`/`course_id` NOT NULL, `context_ref jsonb`, UNIQUE + index đúng.
  - `alembic downgrade 0007_p22_eval_cost` → exit 0 → 15 bảng, 2 bảng + 2 enum tutor biến mất.
  - Seed user/course/unit/lesson ở 0007 (`content_version=3`) → upgrade head → ORM đọc
    `content_version=3`, `status=ready`, `grounding=general_ai_knowledge`, `tutor_threads=0`
    ⇒ **không mất dữ liệu**.
- TESTED (PostgreSQL race, throwaway `p30_tutor_race_check`):
  - `POSTGRES_TEST_URL=…/p30_tutor_race_check python -m pytest tests/test_p30_tutor_postgres_concurrency.py -q`
    → **2 passed**: 6 lần prepare đồng thời cùng `clientMessageId` ⇒ **1 cặp** user+assistant,
    **1 thread**; cross-user thread lookup ⇒ 404.
- TESTED (Docker full stack + E2E, mock provider):
  - Backup trước khi rebuild: `docker exec db pg_dump` → `backup_pre_p30_tutor_20261031_202153.sql`.
  - Backend tự chạy `alembic upgrade head` → DB dev `ailp` ở `0008_p30_tutor_core`; health 200.
  - Flag **TẮT**: `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **52/52 PASS**
    (12 = 503 `TUTOR_DISABLED`).
  - Flag **BẬT** (`TUTOR_ENABLED=true docker compose up -d backend`) → **58/58 PASS**: stream
    delta→done (329 ký tự, seq đúng), history đúng thứ tự, retry `replayed=true` cùng messageId,
    blockIndex ngoài biên 422, chèn `systemPrompt` 422, user B 404 thread/list, thiếu CSRF 403.
  - Trả về mặc định (`docker compose up -d backend`, `TUTOR_ENABLED=false`) → E2E lại **52/52**.
- NOT TESTED:
  - **Real provider streaming** (OpenAI-compatible thật, tốn phí): parser đã test bằng
    `httpx.MockTransport`, nhưng chưa gọi endpoint thật ⇒ chất lượng/latency/token thật của tutor
    là **NOT TESTED**, không được coi là đã kiểm chứng.
  - Chất lượng sư phạm câu trả lời: mock trả template; chưa có người chấm.
  - Resume `Last-Event-ID`, stop server-side, tool allowlist, allowance đầy đủ (P3.1).
  - Browser E2E (Playwright) cho UI stream/stop: build + typecheck OK nhưng chưa chạy trình duyệt.
- BLOCKED: none cho P3.0. Real streaming cần phê duyệt ngân sách/dữ liệu gửi ra ngoài.
- Database: **có migration** `0008_p30_tutor_core` (expand-only; upgrade/downgrade/legacy-row đã
  kiểm chứng trên DB throwaway; DB dev đã backup + upgrade).
- Security: ownership 404; contextRef resolve server-side + kiểm biên; answer key không vào prompt;
  `extra=forbid` chặn client chèn prompt/nội dung; CSRF + burst rate limit; log không chứa prompt,
  key hay nội dung học viên; SSE `no-store`; lỗi provider chỉ lộ mã.
- Regressions: 0. pytest 270 → **306 passed / 12 skipped**; E2E 52/52 (off) và 58/58 (on); build OK.
- Known limitations:
  - Chưa có endpoint stop server-side: dừng ở client ⇒ server ghi `cancelled`, nhưng provider có
    thể đã tính phí phần đã sinh (không hoàn tiền).
  - `TUTOR_MESSAGES_PER_DAY` là trần đơn giản, chưa phải allowance token/quota phân tán.
  - Thread listing chưa phân trang UI (API có limit/offset).
- PHASE GATE: **PASS cho P3.0 (Tutor Core, mock streaming)** — T-012/T-013 có bằng chứng; real
  provider streaming ghi rõ **NOT TESTED**, không tuyên bố PASS.
- NEXT: **P3.1** (tool read-only allowlist, stop/cancel server-side, quota/allowance đầy đủ) hoặc
  **P4.0** PDF ingestion nếu ưu tiên nguồn tài liệu.

## 2026-10-31 — P2.2 AI Evaluation, Safety, Quality & Cost Control
- Base commit: `0f2fd31886338620cc3967e4f5685bf4a54a32ec` (branch `main`, working tree)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Tách 3 tầng đánh giá, không trộn**: (1) rubric **deterministic** (schema/lint/DAG/quiz/
    độ dài/trùng lặp/ngôn ngữ) là **cổng pass/fail duy nhất**; (2) `HUMAN_RUBRIC` 9 tiêu chí 0–4
    cho **người chấm**; (3) **LLM-as-judge** chỉ là tín hiệu tham khảo có metadata, không là
    ground truth. Không claim "AI chính xác" từ JSON hợp lệ.
  - **Cost trung thực**: `cost_estimate_usd = NULL` khi chưa cấu hình giá model ⇒ nghĩa là
    *chưa biết*, **không phải 0/miễn phí**. API trả kèm `costKnown` để client/report phân biệt.
  - **Usage là metadata, không phải nội dung**: bảng `llm_usage_events` không lưu prompt, câu trả
    lời người học hay nội dung sinh ra; chỉ provider/model/kind/token/latency/finish_reason/cost.
  - **Budget chặn trước khi đốt thêm tiền**: vượt `GENERATION_MAX_TOKENS_PER_JOB` hoặc
    `GENERATION_MAX_COST_USD_PER_JOB` ⇒ job `failed` `BUDGET_EXCEEDED`, **fatal** (retry chỉ tốn
    thêm). Mock (không báo usage) không bị chặn oan.
  - **Đo cả chi phí ngoài job**: interview/proposal xảy ra trong request, không thuộc job — vẫn
    ghi usage bằng session riêng (best-effort) vì chi phí đã phát sinh kể cả khi request rollback.
  - **Proposal/lesson cũng có bounded schema repair** (trước P2.2 chỉ interview): giảm việc cả
    job fail vì một block sai trong khi `LLM_MAX_SCHEMA_RETRIES` vẫn chặn số request.
  - Dataset 12 topic cố định (vi/en, beginner→advanced, có `ambiguous`) với kỳ vọng **thuộc tính
    cấu trúc**, không so khớp chuỗi tự do; ngưỡng rubric/regression là **PROPOSAL**.
- IMPLEMENTED:
  - `backend/app/providers/usage.py` (mới): `UsageRecord`/`UsageCollector` (ContextVar, cô lập
    theo task), `parse_pricing`/`resolve_price`/`estimate_cost_usd`, `Stopwatch`.
  - `backend/app/services/llm_usage_service.py` (mới): `flush_usage` (event + cộng dồn job),
    `record_standalone` (session riêng, best-effort), `enforce_job_budget`, `JobBudgetExceeded`.
  - `backend/app/providers/openai_compatible_provider.py`: ghi usage mỗi lời gọi, `kind="judge"`,
    `request_json()` cho evaluator, bounded schema repair cho proposal/lesson.
  - `backend/app/providers/base.py`: hook `request_json` mặc định từ chối (không giả điểm judge).
  - `backend/app/models/models.py`: `LlmUsageEvent` + 4 cột usage trên `GenerationJob`.
  - `backend/alembic/versions/0007_p22_eval_cost.py` (mới): bảng + 2 index + 4 cột (expand-only).
  - `backend/app/worker/generation.py`: `collect_usage()` quanh generation, flush sau mỗi bài,
    flush cả khi lỗi (rollback nội dung trước, ghi usage sau), enforce budget.
  - `backend/app/services/course_service.py`: ghi usage interview/proposal qua session riêng.
  - `backend/app/services/job_service.py`: `BUDGET_EXCEEDED` là lỗi fatal.
  - `backend/app/schemas/schemas.py` + `api/v1/routes.py`: `GenerationOut` có
    `llmCalls/promptTokens/completionTokens/costEstimateUsd/costKnown`.
  - `backend/evals/`: `dataset.py` (12 topic), `rubric.py` (deterministic + `HUMAN_RUBRIC` +
    `THRESHOLDS`), `judges.py` (LLM-as-judge có metadata + `not_run`), `pipeline.py`,
    `regression.py` (ngưỡng, `comparable=False` khi khác provider/prompt/dataset), `runner.py` (CLI
    `--provider/--all/--topics/--judge/--yes/--compare`).
  - `backend/app/core/config.py`, `.env.example`, `docker-compose.yml`: `LLM_PRICING_JSON`,
    `LLM_MAX_OUTPUT_TOKENS_JUDGE`, `GENERATION_MAX_TOKENS_PER_JOB`,
    `GENERATION_MAX_COST_USD_PER_JOB` cho cả backend/worker/beat.
  - Frontend `new/generating`: hiển thị số lời gọi/token và cảnh báo "chưa cấu hình giá model".
  - `backend/e2e_acceptance.py`: +1 check (5e usage/cost metadata) → **51 check**.
- TESTED (offline, SQLite):
  - `cd backend && python -m pytest -q` → **270 passed, 10 skipped** (22.1s; trước 232/10).
    Mới: `tests/test_p22_eval.py` (**18 test**: dataset ≥10/đa dạng/5 đáp án/id lạ, rubric pass
    clean course, fail thiếu quiz/thiếu bài/teach quá ngắn/cảnh báo trùng câu hỏi, thresholds hợp
    lệ, judge mock ⇒ `not_run` không điểm giả, judge parse 0–4 bỏ giá trị ngoài range/khoá lạ,
    pipeline mock deterministic + label `mock`, summary, regression identical/major drop/judge
    drop/incomparable) và `tests/test_p22_cost_budget.py` (**18 test**: pricing parse/resolve
    wildcard/giá âm, cost NULL≠0, adapter ghi usage đúng kind/token/reasoning/finish_reason,
    collector cô lập, budget token/cost, `BUDGET_EXCEEDED` fatal, flush ghi event + cộng dồn job,
    pricing thiếu ⇒ NULL, flush không nhân bản, migration 0007 chain/expand-only, metadata columns,
    `GenerationOut` usage fields, worker ghi usage thật + job dừng khi vượt budget, request path
    ghi usage dù provider lỗi).
  - `python -m evals.runner --provider mock --all` → **12/12 topic pass**, 0 request, cost
    `None` (mock không tốn tiền, không có usage).
  - `cd frontend && npx tsc --noEmit` → 0 lỗi; `npm run build` → OK (9 routes).
- TESTED (PostgreSQL throwaway `p22_migration_check`):
  - `alembic upgrade head` → `0007_p22_eval_cost (head)`; `\d llm_usage_events` có đủ cột + 2
    index + FK job/user; `generation_jobs.llm_calls` NOT NULL default 0.
  - `alembic downgrade 0006_p2sr_source_research` → bảng và 4 cột bị drop (đếm = 0).
  - Seed legacy ở 0006 (user/course/job `ready`) → upgrade head → `llm_calls=0`, các cột token/
    cost NULL ⇒ **không mất dữ liệu**.
- TESTED (Docker full stack, mock): `docker compose up -d --build backend worker` +
  `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **51/51 PASS**, backend tự
  upgrade DB dev `ailp` lên 0007 (backup `backup_pre_p22_20261031_192458.sql`, 14 COPY).
- TESTED (real provider — Deploy.com `deepseek-ai/deepseek-v4.1-flash-1017`, người dùng đã duyệt):
  - `python -m evals.runner --provider openai --all --judge --yes` → **12/12 topic pass**
    (deterministic), 149 request (không tính judge), **103.984 prompt / 339.926 completion** tokens;
    thời gian 105–223s/topic. `costEstimateUsd=null` vì `.env` không cấu hình `LLM_PRICING_JSON`
    ⇒ báo cáo ghi đúng "chưa biết giá".
  - Judge: **11/12 scored**, trung bình **3.17/4**; `en-beginner-excel` **`status=error`**
    (`PROVIDER_BUDGET_EXCEEDED` do output bị cắt ở trần judge) — **không** sinh điểm giả.
    So sánh mock↔real: `comparable=false`, `passed=true` (không kết luận regression chéo provider).
  - Real Docker E2E (`LLM_PROVIDER=openai`, `E2E_GENERATION_TIMEOUT=1800`,
    `LLM_PRICING_JSON` set): **51/51 PASS**; DB ghi job thật
    `llm_calls=10, prompt=7551, completion=23146, cost≈$0.027498`; tổng `llm_usage_events`
    lesson 23 / proposal 1 / interview 1, cost ≈ $0.0638 trong phiên test.
  - Trường hợp biên gặp và xử lý: một job `PROVIDER_SCHEMA_INVALID` "mc có option trùng" ở unit_2
    (retry thủ công trong E2E chạy lại thành công); output cắt `finish_reason=length` được escalate
    budget provider như thiết kế. Đã trả `LLM_PROVIDER` về `mock` và bỏ `LLM_PRICING_JSON` sau test.
- NOT TESTED:
  - **Điểm rubric của người chấm** cho 12 topic (không có người chấm thật trong phiên này); judge
    không thay thế.
  - Độ chính xác **factual** của nội dung: rubric deterministic không kiểm tra đúng/sai chuyên môn.
  - Cost tuyệt đối chỉ đúng khi `LLM_PRICING_JSON` khớp bảng giá thực của provider.
  - Regression giữa 2 prompt version thật (chưa có baseline prompt khác).
- BLOCKED: none cho hạ tầng P2.2. Chấm chất lượng bằng người là việc cần người thật.
- Database: **có migration** `0007_p22_eval_cost` (expand-only; upgrade/downgrade/legacy-row đã
  kiểm chứng trên DB throwaway; DB dev đã backup + upgrade).
- Security: usage chỉ chứa metadata, không prompt/PII/key; `LLM_PRICING_JSON` và `LLM_API_KEY` chỉ
  ở env server; judge là evaluator, không nằm trên đường đi của người học; budget chặn job thay vì
  để tiêu vô hạn; API không lộ chi tiết provider.
- Regressions: 0. pytest 232 → **270 passed**; E2E 50 → **51/51**; build OK.
- Known limitations:
  - Judge có thể bị cắt output với course 9 bài; hiện ghi `status=error` (trung thực) chứ không
    tự chia nhỏ. Có thể nâng `LLM_MAX_OUTPUT_TOKENS_JUDGE` hoặc chấm theo batch sau.
  - `minTeachRatio`/`lessonQuizAlignment`/ngôn ngữ là **warning** (không chặn) vì mock hợp lệ có
    1 teach + 5 quiz; ngưỡng cần hiệu chỉnh bằng dữ liệu thật.
  - Chưa có dashboard chi phí tổng hợp theo user/thời gian (bảng event đã sẵn sàng truy vấn).
- PHASE GATE: **PASS cho P2.2** (rubric deterministic + dataset + cost/budget + regression + real
  eval 12/12 có bằng chứng; human rubric ghi rõ NOT TESTED/BLOCKED).
- NEXT: **P3.0 AI Tutor Core** (SSE + lesson grounding, nền P3.0b đã có) — hoặc P4.0 PDF ingestion
  nếu ưu tiên nguồn tài liệu.

## 2026-10-31 — P2.SR Source Research Agent Foundation
- Base commit: `5e5f9cd496a22e6c1b10b535efd1fdeece43c6c9` (branch `main`, working tree có P2.1 + P3.0b chưa commit)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Agent độc lập, không phải sub-agent IDE.** Package `backend/app/agents/source_research/` tách khỏi
    `course_service`; Course Orchestrator vẫn giữ điều phối.
  - **Không LLM trong agent phase này.** Topic analysis + ranking đều deterministic ⇒ test offline,
    không chi phí API, giải thích được từng quyết định.
  - **Agent không chạm DB.** Persistence do `services/source_research_service.py` thực hiện với
    identity/ownership server-side; agent chỉ nhận `saver` (không dùng để ghi kết quả thật).
  - **Chỉ 2 mức kiểm chứng thuộc agent** (`discovered`, `metadata_verified`). Validator ở
    `ResearchResult` **từ chối** `content_available`/`evidence_verified` ⇒ bảo đảm ở tầng dữ liệu,
    không chỉ là quy ước. Mock luôn bị ép `discovered`.
  - **Policy theo lĩnh vực**, không dùng một trust score: programming ưu tiên official docs/spec,
    medicine ưu tiên clinical guideline/systematic review/government health, general ưu tiên
    curriculum/university/textbook.
  - **Không nhân bản adapter discovery:** dùng lại `app/services/source_discovery.py` qua bridge.
  - **Mặc định TẮT** (`SOURCE_RESEARCH_ENABLED=false`, `SOURCE_RESEARCH_AUTO_LINK=false`) để bảo toàn
    regression; flag tắt ⇒ endpoint trả `503 SOURCE_RESEARCH_DISABLED`, worker không chạy agent.
- IMPLEMENTED:
  - `backend/app/agents/source_research/`: `agent.py` (workflow bounded), `schemas.py` (input/output
    contract + validator), `policies.py`, `ranking.py` (dedupe + scoring + verification), `topic.py`,
    `tools.py` (allowlist + budget + timeout + input validation), `adapters/{base,mock}.py`.
  - `backend/app/services/source_research_service.py` (mới): resolve adapter, fingerprint sha256,
    idempotent run, stale-run recovery, `link_verified_sources`, worker hook.
  - `backend/app/api/v1/research.py` (mới): 4 endpoint + CSRF + rate limit + ownership 404.
  - `backend/app/models/models.py`: `SourceResearchStatus` + `SourceResearchRun`; export trong
    `app/models/__init__.py`.
  - `backend/alembic/versions/0006_p2sr_source_research.py` (mới): bảng + enum + 3 index +
    UNIQUE(course_id, request_fingerprint); expand-only.
  - `backend/app/core/config.py`: 7 cấu hình P2.SR; `.env.example`; `docker-compose.yml` (cả 3 service).
  - `backend/app/worker/generation.py`: gọi `maybe_auto_link_for_generation` (flag-guarded, lỗi không
    làm job failed).
  - `backend/app/schemas/schemas.py`: `ResearchRequestIn` (không có courseId/ownerId), `ResearchSourceOut`,
    `ResearchRunOut`, `ResearchRunListOut`.
  - `backend/e2e_acceptance.py`: +5 check (S1–S5) chạy cả hai chế độ flag.
  - `docs/source-research-agent.md` (mới), cập nhật `architecture.md`, `database-design.md`,
    `SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`.
- TESTED (offline, SQLite):
  - `cd backend && python -m pytest -q` → **232 passed, 10 skipped** (19.72s; trước 190/9).
    Mới: `tests/test_source_research_agent.py` (**21 test**: topic analysis ví dụ "Python for AI",
    medicine policy, domain fallback, input bounds, canonical-URL dedupe, ranking official-vs-blog,
    medicine guideline-vs-blog, mock determinism + no-socket, empty catalog ⇒ insufficient, max
    sources, maxSources=20 clamp, tool budget, adapter timeout, config failure, invalid tool input,
    curated-only tool, saver), `tests/test_p2sr_integration.py` (**16 test**: persist run, idempotent
    retry, cross-user 404 (list/get/accept), flag off 503, CSRF 403, adapter failure ⇒ failed row,
    accept mock ⇒ 409, accept curated ⇒ link + DB vẫn `unverified` + re-accept không nhân bản,
    provider `web`/lạ ⇒ 503 có mã, body cấm override `courseId`/`ownerId` + bounds 422, flag off
    generation không tạo run, auto-link curated khi bật (lesson vẫn `general_ai_knowledge`), failed
    run retry không nhân bản row, toàn bộ agent vượt timeout ⇒ failed run (không treo)),
    `tests/test_p2sr_migration_contract.py` (**5 test**).
  - `cd frontend && npm run build` → OK (9 routes, không đổi UI nên bundle tương đương).
- TESTED (PostgreSQL throwaway `p2sr_migration_check`):
  - `alembic upgrade head` → exit 0 → `0006_p2sr_source_research (head)`, 14 bảng, enum
    `source_research_status`, index/UNIQUE đúng.
  - `alembic downgrade 0005_p30_source_registry` → exit 0 → bảng P2.SR và enum bị drop, 13 bảng còn lại.
  - Seed user/course/unit/lesson ở revision 0005 (`content_version=3`) → upgrade head → ORM đọc được
    `grounding=general_ai_knowledge`, `content_version=3`, course `ready` ⇒ **không mất dữ liệu**.
- TESTED (PostgreSQL race, throwaway `p2sr_race_check`):
  - `POSTGRES_TEST_URL=…/p2sr_race_check python -m pytest tests/test_p2sr_postgres_concurrency.py -q`
    → **1 passed**: 6 request đồng thời cùng fingerprint ⇒ **1 research run** (1 created, 5 reused).
- TESTED (Docker full stack + E2E, mock provider):
  - Backup trước khi rebuild: `docker exec db pg_dump` → `backup_pre_p2sr_20261031_173653.sql` (13 COPY).
  - Backend container tự chạy `alembic upgrade head` → DB dev `ailp` ở `0006_p2sr_source_research`.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` **flag TẮT** → **50/50 PASS**
    (S1 = 503 `SOURCE_RESEARCH_DISABLED`, S4/S5 cross-user 404 + CSRF 403).
  - Chạy lại với `SOURCE_RESEARCH_ENABLED=true SOURCE_RESEARCH_PROVIDER=mock` → **52/52 PASS**
    (S1 run completed 3 nguồn deterministic, S2 reused=true, S3 accept mock ⇒ 409).
  - Trả môi trường về mặc định (`docker compose up -d` không set env) → E2E lại **50/50 PASS**.
- NOT TESTED:
  - Nguồn thật (Crossref/OpenAlex/arXiv/web): **chưa triển khai**, không có network call nào được chạy.
  - Kiểm chứng nội dung nguồn / citation thật: **không thể** vì chưa ingest (P4).
  - LLM trong agent: không dùng; chất lượng topic analysis trên chủ đề lạ chỉ được test bằng rule.
  - UI research run: **NOT IMPLEMENTED** (chỉ API).
- BLOCKED: none cho P2.SR. P4 bị chặn bởi ingestion pipeline (chưa có).
- Database: **có migration** `0006_p2sr_source_research` (expand-only; upgrade/downgrade/legacy-row đã
  kiểm chứng trên DB throwaway; DB dev đã upgrade; backup trước khi thao tác).
- Security: ownership server-side (404); agent không truy cập DB/network/FS; adapter `web` từ chối;
  mock không bao giờ auto-link; `accept` từ chối run mock; goals/level người học **không** gửi ra
  adapter; CSRF + rate limit; log chỉ id/adapter/status/số nguồn.
- Regressions: 0. pytest 190 → **232 passed**; E2E 47 → **50/50** (flag off) và **52/52** (flag on);
  build OK; quiz/XP/progress/interview/proposal không đổi.
- Known limitations:
  - `metadata_verified` = kiểm tra **cấu trúc** metadata, không phải "nguồn đáng tin".
  - Relevance là so khớp từ khoá bề mặt; topic analysis rule-based.
  - `SOURCE_RESEARCH_PROVIDER=web` lỗi cấu hình có chủ đích.
  - Chưa có UI; chưa có eval chất lượng chọn nguồn.
- PHASE GATE: **PASS cho P2.SR** (AC01–AC13 có bằng chứng; AC13 = `docs/source-research-agent.md` §11).
- NEXT: P4.0 PDF ingestion + provenance (storage/extract/chunk/idempotent worker) trước khi bất kỳ
  `source_grounded`/`locator_verified` nào được bật.

## 2026-10-31 — P3.0b Source Registry, Evidence Contract & Source-First Integration
> Ghi chú đánh số: `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` dùng **P3.0–P3.1 cho AI Tutor**.
> Việc này là nhánh **P3.0b (Source-First foundation)** chèn trước P4 vì nó không phụ thuộc Tutor
> và là điều kiện để citation P4 có chỗ bám. Revision id giữ tên `0005_p30_source_registry`.
- Base commit: `5e5f9cd496a22e6c1b10b535efd1fdeece43c6c9` (branch `main`, working tree có P2.1 chưa commit)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Source-First nhưng trung thực về giới hạn:** P3.0 chỉ thêm *metadata* nguồn + contract citation.
    Chưa ingest PDF/web, chưa chunk, chưa embedding/vector ⇒ **không** có grounding thật.
  - **Bốn cấp kiểm chứng tách biệt** (metadata / locator / evidence supports claim / corroborated)
    được mã hoá thành 2 enum riêng, không gộp thành một "trust score".
  - **Model không được cấp `sourceId`** ⇒ citation chỉ do server sinh từ registry; không thể bịa.
  - **Evaluator deterministic metadata-only** (không đọc nội dung). Thiếu dữ liệu ⇒ `unknown` và
    loại khỏi mẫu số; coverage < 0.5 ⇒ `insufficient_metadata`, `weightedScore=None`.
  - `lessons.grounding` server_default `general_ai_knowledge` ⇒ bài học cũ đọc được, hiểu đúng là
    chưa kiểm chứng. Course có nguồn nhưng chưa ingest **vẫn** là `general_ai_knowledge`.
  - Discovery: interface adapter + `curated` (catalog env) + `mock` (deterministic, no network);
    adapter `web` từ chối 503 thay vì âm thầm gọi mạng.
- IMPLEMENTED:
  - `backend/app/models/models.py`: `SourceType`, `SourceVisibility`, `SourceVerificationStatus`,
    `CitationValidationStatus`, `LessonGrounding` + model `Source`, `CourseSource`,
    `LessonCitation`, cột `Lesson.grounding`.
  - `backend/alembic/versions/0005_p30_source_registry.py` (mới): 3 bảng + 1 cột + enum + index,
    `upgrade`/`downgrade` đối xứng, idempotent theo inspector.
  - `backend/app/services/source_service.py` (mới): create idempotent (dedupe_key sha256), ownership
    (public hoặc owner), link/unlink course, load cho worker scoped theo `course.user_id`.
  - `backend/app/services/source_evaluation.py` (mới): 6 tiêu chí có trọng số, công thức chuẩn hoá
    theo trọng số **có dữ liệu**, license hạn chế chặn `metadata_verified`.
  - `backend/app/services/citation_service.py` (mới): `validate_citation_locator` (source_changed /
    unavailable / unverified / rejected — **không bao giờ** evidence_supported), replace/list.
  - `backend/app/services/source_discovery.py` (mới): `curated`, `mock`, `web` placeholder;
    `get_discovery_adapter` fail rõ ràng.
  - `backend/app/services/source_context.py` (mới): build context, quyết định grounding (chỉ khi có
    excerpt thật), câu thông báo.
  - `backend/app/api/v1/sources.py` (mới): POST/GET sources, discover (khai báo trước route động),
    evaluation, POST/GET `/v1/courses/{id}/sources`.
  - `backend/app/schemas/schemas.py`: source/citation/discovery schemas; `LessonOut` +
    `grounding`/`citations`/`evidenceNotice` (backward-compatible default).
  - `backend/app/worker/generation.py`: source resolution theo course; `generate_lesson(..., source_context)`;
    ghi `grounding` + `replace_lesson_citations`; snapshot evaluation vào `course_sources`.
  - `backend/app/providers/*`: `generate_lesson` nhận `source_context` (mock + openai-compatible);
    prompt `p3.0-v1` cấm model tự tạo URL/số trang/sourceId; delimiter chống prompt injection.
  - `backend/app/core/config.py`: `source_discovery_adapter`, `source_curated_catalog`,
    `source_context_enabled`, `source_context_max_chars`.
  - Frontend: `lib/api.ts` (SourceOut/Citation + nhãn trạng thái + `isVerifiedStatus`), course page
    hiển thị danh sách nguồn + publisher/URL/version/ngày cập nhật + badge trạng thái, lesson page
    hiển thị citation + notice "chưa xác minh"; CSS mới (`.notice-box`, `.badge-muted`, `.source-list`,
    `.evidence-quote`).
  - `backend/e2e_acceptance.py`: +10 check P3.0 (11, 11b–11h, B5, B6).
- TESTED (offline):
  - `cd backend && python -m pytest -q` → **190 passed, 9 skipped** (42.27s; các lần chạy trước 44.86s và 97.41s khi máy bận). Mới: `tests/test_p30_source_first.py` (**26 test**): metadata round-trip, duplicate
    idempotent, public reuse, invalid input (6 case), CSRF, private cross-user 404, link chéo bị chặn,
    many-sources-per-course, discovery deterministic + no-socket monkeypatch, network adapter 503,
    evaluation unknown/insufficient/license, citation contract (unavailable/source_changed/rejected/
    không tự evidence_supported), lessons có/không nguồn, FK citation, source-context helpers.
  - `npx tsc --noEmit` → 0 lỗi; `npm run build` → OK (9 routes).
  - `tests/test_p30_migration_contract.py` (**4 test**): revision chain nối 0004, upgrade+downgrade
    callable, upgrade không drop cột/bảng cũ, metadata có đủ 3 bảng + `lessons.grounding` + constraints.
  - E2E (`E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py`, Docker full stack, mock)
    → **47/47 PASS**, gồm: tạo nguồn unverified, dedupe, evaluation metadata-only, link course, lesson
    có nguồn nhưng grounding=`general_ai_knowledge` + 1 citation `unverified`, answer key không lộ,
    user B bị 404 ở source/course-sources/lesson, CSRF 403.
- TESTED (migration, PostgreSQL throwaway `p30_migration_check`):
  - `alembic upgrade head` → exit 0 → 13 bảng + enum `lesson_grounding` + `lessons.grounding`
    NOT NULL default `'general_ai_knowledge'`.
  - `alembic downgrade 0004_p12_job_reliability` → exit 0 → còn 10 bảng, cột/enum P3.0 bị drop,
    enum course/job/lesson giữ nguyên.
  - Seed lesson "legacy" ở 0004 → upgrade head → ORM đọc `grounding=general_ai_knowledge`, version
    giữ nguyên ⇒ **AC08 đạt**.
  - DB dev thật (`ailp`) đã upgrade lên `0005_p30_source_registry` qua entrypoint container; backend
    health 200, E2E 47/47.
- TESTED (PostgreSQL race/idempotency, throwaway DB `p30_race_check` — đã drop sau test):
  - `POSTGRES_TEST_URL=…/p30_race_check python -m pytest tests/test_p30_postgres_concurrency.py -q`
    → **3 passed**: 8 request đồng thời tạo cùng nguồn ⇒ **1 row** (1 created, 7 reused); 6 request
    đồng thời link cùng course↔source ⇒ **1 row**; cross-user đọc nguồn private ⇒ `SourceAccessError`.
  - Regression suite PostgreSQL cũ vẫn xanh: `test_p11_postgres_concurrency.py` → 2 passed;
    `test_p12_postgres_concurrency.py` → 4 passed.
- NOT TESTED:
  - Grounding thật / locator verification / evidence-supported: **không thể** vì chưa ingest nội dung.
  - PDF ingestion, chunking, embedding, pgvector retrieval, web/arXiv fetch (P4).
  - Real-provider lesson generation **có** source_context (chỉ mock được test; không gọi API thật
    để tránh chi phí ngoài phạm vi).
  - (đã bổ sung) Concurrency race test trên PostgreSQL thật — xem mục TESTED (PostgreSQL) bên dưới.
- BLOCKED: none cho P3.0. P4 bị chặn bởi việc chưa có ingestion pipeline + storage adapter.
- Database: **có migration** `0005_p30_source_registry` (expand-only, rollback đã kiểm chứng).
- Security: ownership server-side (404, không 403 → không xác nhận tồn tại); model không nhận
  sourceId; nguồn mới luôn unverified; discovery không network; log chỉ id/type/visibility; không
  lưu secret/PII trong source; license hạn chế chặn metadata_verified.
- Regressions: 0. pytest 160 → **190 passed, 9 skipped**; E2E 37 → **47/47**; build/tsc OK; quiz/XP/progress/interview không đổi.
- Known limitations:
  - `evidence_supported`/`corroborated` **chưa từng** được tạo ra — đúng thiết kế cho P3.0.
  - `consistency` luôn `unknown`; `relevance` chỉ keyword bề mặt.
  - Chưa có UI tạo nguồn / duyệt nguồn / discover (API sẵn sàng; UI hiển thị là chính).
  - `content_hash`/`version` lưu nhưng chưa dùng để phát hiện nguồn đổi (chờ ingestion P4).
- PHASE GATE: **PASS cho P3.0 (phạm vi Source Registry + contract)** — AC01–AC11 có bằng chứng;
  AC12 (tài liệu chuyển sang RAG) ở `docs/source-first-architecture.md` §8.
- NEXT: P4.0 PDF ingestion + provenance (storage, extraction, chunking, idempotent worker) trước khi
  bật bất kỳ grounding thật nào.

## 2026-10-31 — P2.1 AI Course Generator + Pedagogy DAG
- Base commit: `5e5f9cd496a22e6c1b10b535efd1fdeece43c6c9` (branch `main`, working tree)
- New commit/branch: **NOT COMMITTED** (working tree)
- Scope & decisions:
  - **Hồ sơ người học do SERVER suy ra** (`services/pedagogy.extract_learner_profile`, rule-based, deterministic) từ chính 5 câu trả lời; **không** tin field model tự khai và **không** suy diễn thuộc tính nhạy cảm (tuổi/giới/sức khỏe/quốc tịch/tôn giáo).
  - **Curriculum = DAG prerequisite**: mỗi bài đúng 1 skill (id, tiêu đề, Bloom level, outcome); chuẩn hoá bỏ self-loop/cạnh trùng/cạnh ngược thứ tự bài; **chu trình thật ⇒ 502 `PROPOSAL_SCHEMA_INVALID`** (không tự sửa lặng lẽ). Kiểm chứng bằng Kahn topological sort.
  - Dữ liệu curriculum nằm trong `course_proposals.payload` (JSON) ⇒ **không cần migration**, proposal cũ (thiếu field) vẫn đọc được; `pedagogy.fill_skills` lấp skill thiếu để không có bài "mồ côi".
  - Generation vẫn phân cấp proposal → unit → lesson và dùng **proposal snapshot** của P1.2 (`job.proposal_version`); worker chuẩn hoá lại curriculum để proposal legacy cũng có skill/outcome.
  - **Answer key giữ nguyên contract P1.1**: LLM tạo đáp án nhưng chỉ tồn tại trong `lessons.content` (private); API vẫn trả `public_blocks`; chấm vẫn deterministic.
- IMPLEMENTED:
  - `backend/app/schemas/schemas.py`: `LearnerProfile`, `CurriculumSkill` (+`BLOOM_LEVEL`), `ProposalPayload.learnerProfile/skills/prerequisites` (optional, backward-compatible).
  - `backend/app/services/pedagogy.py` (mới): `extract_learner_profile` (level/time/style/depth + warnings), `lesson_order`, `fill_skills`, `normalize_curriculum`, `validate_curriculum` (DAG), `curriculum_summary` (topological order + Bloom cao nhất).
  - `backend/app/providers/validation.py`: `validate_proposal` gọi normalize+validate curriculum; `validate_lesson` thêm lint câu hỏi trùng và đoạn giảng lặp nguyên văn.
  - `backend/app/providers/openai_compatible_provider.py`: prompt `p2.1-v1` (interview 5 khía cạnh + cấm thông tin nhạy cảm; proposal có skills/prerequisites/Bloom; lesson có skill+prerequisite context); `_structured()` retry **bounded** khi sai schema kèm mô tả lỗi.
  - `backend/app/providers/mock_provider.py`: proposal deterministic có 4 skill + chuỗi prerequisite tuyến tính.
  - `backend/app/services/course_service.py`: server gắn `learnerProfile`, chuẩn hoá/validate curriculum trước khi lưu; map lỗi curriculum → 502.
  - `backend/app/worker/generation.py`: chuẩn hoá curriculum từ snapshot; `job.stage` theo unit (`unit_k/N`) để quan sát tiến độ phân cấp.
  - Frontend `new/proposal`: card **Hồ sơ học viên** (level/độ sâu/thời gian/ phong cách/mục tiêu/warning) + card **Lộ trình kỹ năng** (Bloom badge, "Cần học trước"); CSS `.profile-box`, `.curriculum-list`, `.muted`.
  - `backend/e2e_acceptance.py`: +2 check (3b learner profile, 3c DAG phủ đủ bài) → **37/37**; `E2E_GENERATION_TIMEOUT` để chạy cùng script với provider thật.
  - `backend/evals/real_provider_eval.py` (mới, opt-in `--yes`): eval 3 topic thật, đo schema/curriculum/lesson + latency/token; report JSON gitignored.
- TESTED (offline):
  - `python -m pytest -q` → **160 passed, 6 skipped** (25.8s). Mới: `tests/test_p21_pedagogy.py` (24 test: profile, DAG cycle/prune, lesson lint, API proposal, eval 10 topic mock) + 12 test trong `test_llm_provider.py` (prompt version/nội dung, profile trong prompt, skill context, cycle từ LLM bị từ chối, budget theo loại call, escalation bounded, schema repair bounded).
  - `npm run build` → OK (9 routes); `npx tsc --noEmit` → 0 lỗi.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` (mock, Docker full stack) → **37/37 PASS**.
- TESTED (real provider — Deploy.com `deepseek-ai/deepseek-v4.1-flash-1017`, được người dùng duyệt ngân sách):
  - `python -m evals.real_provider_eval --topics 3 --yes` → **3/3 topic pass** (31 request; 18.365 prompt / 63.163 completion tokens; 138–154s/topic): `vi-beginner-tech` 9/9 bài, `vi-advanced-social` 8/8 bài (10 edge), `en-advanced-eng` 8/8 bài. Trường hợp biên gặp và đã xử lý: output JSON bị cắt (`finish_reason=length`) và model trả thiếu câu hỏi (schema repair).
  - **Real E2E qua Docker + Celery worker** (`LLM_PROVIDER=openai`, `E2E_GENERATION_TIMEOUT=1200`): **37/37 PASS** — 9 bài thật, `contentVersion=2` sau retry, quiz 3/3 (XP 50), attempt idempotent, cross-user 404, stale version 409. Worker log: `llm call ok ... finish_reason=stop` ×10, `Task ... succeeded` 134s và 141s, 0 Traceback.
  - Đã **trả môi trường về `LLM_PROVIDER=mock`** sau test; E2E mock lại 37/37.
- NOT TESTED:
  - Chất lượng **sư phạm/factual** của nội dung (script chỉ đo schema/curriculum/lint deterministic; rubric người chấm thuộc P2.2).
  - Eval real quy mô lớn (10+ topic thật) và benchmark prompt version khác; chi phí tiền tệ chính xác (provider không trả giá).
  - Streaming, OCR/RAG, Tutor (ngoài phạm vi P2.1).
- BLOCKED: none.
- Database: **không migration** (curriculum nằm trong JSON payload), revision vẫn `0004_p12_job_reliability`.
- Security: profile không chứa thuộc tính nhạy cảm (có test); answer key vẫn server-only (E2E 7b `leaked=[]`); API không lộ chi tiết provider; log chỉ metadata (`finish_reason`/token), không prompt/key; API key chỉ ở `.env` và env container (không commit, không log); schema repair và escalation **bounded** để không đốt tiền.
- Regressions: 0. pytest 119 → 160; E2E 35 → 37.
- Known limitations:
  - `extract_learner_profile` là **rule-based tiếng Việt/Anh** (từ khóa); câu trả lời quá ngắn có thể thiếu time/level → warning, không bịa.
  - Curriculum là snapshot JSON: chưa có bảng skill riêng nên chưa truy vấn "skill → mastery" (P5.0 sẽ cần).
  - Provider reasoning tính `reasoning_tokens` vào `completion_tokens` ⇒ budget check phải dựa trên `finish_reason`; provider không trả `finish_reason` bị coi là truncated (an toàn hơn, có thể retry 1 lần).
- PHASE GATE: **PASS** — 6/6 acceptance P2.1 có bằng chứng (offline mock + real provider + real Docker E2E); sai chu trình DAG bị chặn; answer key không lộ; budget/lint bounded.
- NEXT: **P2.2 AI Evaluation, Safety, Quality & Cost Control** — cần rubric người chấm + ngân sách eval ≥10 topic thật.

## 2026-10-30 — P2.0 LLM Provider Infrastructure (Provider-Neutral)
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - **Fail-fast thay vì fallback**: provider lạ/thiếu key/model/base URL ⇒ `ProviderConfigError` ⇒ API 503 `PROVIDER_NOT_CONFIGURED`. Mock chỉ khi `LLM_PROVIDER=mock`.
  - Provider thật đã được người dùng duyệt cho smoke test: **Deploy.com** (`https://api-cdn.deploy.com/api/v1`) + model `deepseek-ai/deepseek-v4.1-flash-1017`. Key **chỉ** trong `.env` (gitignored), không commit, không log.
  - `LLM_PROVIDER` đã được đưa về `mock` sau smoke test để `docker compose up` không tự phát sinh chi phí.
  - Semantic lint **repair** case đáp án blank bị lộ trong câu (thay bằng `____`) thay vì fail — tránh đốt thêm request mà nội dung vẫn dùng được.
- IMPLEMENTED:
  - `backend/app/providers/base.py`: error taxonomy đầy đủ (`ProviderConfigError`, `ProviderAuthError`, `ProviderTimeoutError`, `ProviderRateLimitError`, `ProviderTransientError`, `ProviderBudgetError`, `SchemaInvalidError`) với `code` + `retryable`.
  - `backend/app/providers/validation.py` (mới): semantic rules interview (đúng 5, không trùng), proposal (unit/bài không trùng, có outcome), lesson (≥1 teach + ≥1 quiz, `answerIndex` bounds, option trùng, blank mask, order/match trùng khóa).
  - `backend/app/providers/openai_compatible_provider.py` (mới): adapter `/chat/completions`, timeout, retry backoff+jitter (tôn trọng `retry-after`), bounded retries, budget token, cắt input theo `LLM_MAX_INPUT_CHARS`, log metadata redacted (`provider/model/prompt_version/tokens` — không key/prompt).
  - `backend/app/providers/__init__.py`: registry `mock | openai | openai_compatible`, `provider_name()`, fail-fast.
  - `backend/app/core/config.py`: `llm_api_key/llm_base_url/llm_model/llm_timeout_seconds/llm_max_retries/llm_max_output_tokens/llm_max_input_chars` + `llm_api_key_resolved`.
  - `backend/app/api/v1/routes.py`: `_provider()` → 503 cấu hình; `course_service._generate_proposal` map `ProviderError` → 503 (không lộ chi tiết).
  - `backend/app/services/job_service.py`: `classify_error` dùng taxonomy provider (`retryable`) thay vì đoán theo kiểu exception.
  - `backend/app/worker/generation.py`: `asyncio.TimeoutError` → `ProviderTimeoutError` để retry đúng.
  - `docker-compose.yml`: truyền `LLM_API_KEY/BASE_URL/MODEL` cho backend/worker/beat.
  - `.env.example`: block cấu hình provider mới. `docs/llm-provider.md` (mới): bật/tắt, taxonomy, validation, riêng tư, rollback.
- TESTED:
  - `python -m pytest -q` → **119 passed, 6 skipped** (13.72s). Mới: `tests/test_llm_provider.py` (28 test mocked HTTP) + `tests/test_provider_config_api.py` (4 test fail-fast API) + 3 test taxonomy trong `test_job_reliability.py`.
  - Mocked HTTP coverage: valid output, JSON hỏng, non-object JSON, sai số câu hỏi, câu trùng, proposal trùng bài, `answerIndex` OOB, thiếu teach, blank lộ đáp án (repair), blank không marker, 429+retry-after (retry rồi thành công + hết retry), 5xx bounded, timeout, connection error, 401 không retry, 400 không lộ body, budget vượt trần token, content rỗng, fail-fast key/model/base URL, provider lạ không phải mock, log không chứa key/prompt, input truncation.
  - `npm run build` không đổi (backend-only phase).
  - `E2E_BASE=… python backend/e2e_acceptance.py` → **35/35 PASS** (mock vẫn là mặc định).
  - **REAL PROVIDER SMOKE TEST (được duyệt, 3 request):** Deploy.com + `deepseek-ai/deepseek-v4.1-flash-1017`
    - interview: 5 câu, schema OK, 4.79s, 150 prompt / 196 completion tokens
    - proposal: 3 unit / 12 bài / 7 outcome, 13.89s, 422 / 1879 tokens
    - lesson: 5 block (`teach`, `mc`, `blank`, `short`), 12.05s, 384 / 1319 tokens
    - Tất cả HTTP 200; log chỉ chứa metadata. Phát hiện + sửa 1 lỗi thật: LLM trả block `blank` có đáp án nằm sẵn trong câu → server mask thành `____` (có unit test).
- NOT TESTED: streaming responses; provider thứ hai (Anthropic) — không triển khai; cost estimate chính xác (provider không trả giá); P2.1 hierarchical generation bằng LLM thật.
- BLOCKED: **P2.0.3 real E2E tự động trong CI** — cần biến môi trường/ngân sách riêng; không đưa key vào CI. P2.1 real e2e cần duyệt thêm budget cho 10 topic eval.
- Database: không đổi schema (revision vẫn `0004_p12_job_reliability`).
- Security: key server-only (`.env`, gitignored, `LLM_PROVIDER=mock` mặc định); API 503 không lộ env; log redacted; input bị cắt; output vượt budget → `ProviderBudgetError`; không có nhánh fallback ngầm.
- Regressions: 0. pytest 84 → 119; E2E 35/35; build OK.
- Known limitations:
  - `LLM_MAX_OUTPUT_TOKENS` cao (1879 token cho proposal) → cần hạ xuống hoặc thêm `max_completion_tokens` theo provider nếu muốn tiết kiệm.
  - `response_format=json_object` là phần mở rộng; provider không hỗ trợ sẽ trả 400 → `SchemaInvalidError`.
  - Chưa lưu `cost_estimate` vào DB job (chỉ log token); P2.2 sẽ làm metrics/cost.
- PHASE GATE: **PARTIAL** — infrastructure + mocked tests + 1 real smoke test đạt; **BLOCKED** phần tự động hoá real-provider trong CI và P2.1 real eval.
- NEXT: P2.1 AI Course Generator + Pedagogy DAG (cần duyệt budget cho 10-topic eval trước khi chạy real).

## 2026-10-30 — P1.3 Frontend UX, Navigation & Session Isolation
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - **Session isolation** không chỉ ở server: client gắn `user.id` + `sessionEpoch` vào mọi query key (`useSessionQueryKey`) và `removeQueries()` khi login/logout. Không có `localStorage` user id nào còn sót.
  - Route guard là **UX** (`useRequireAuth` → `/login?next=…`); ownership vẫn do backend enforce (404).
  - Endpoint mới `GET /v1/courses` — không nhận `userId` từ client, luôn scope theo identity đã xác thực.
  - Interview reload: server không trả nội dung câu trả lời cũ (tránh lộ trên máy khác); UI hiển thị "✓ đã trả lời" cho các câu đã xong và tự nhảy tới câu kế tiếp; đủ 5 câu → chuyển thẳng proposal.
- IMPLEMENTED:
  - `backend/app/services/course_service.py::list_courses`: phân trang `limit/offset`, order theo `updated_at desc`, progress từ attempts (dùng lại `_completed_lesson_ids`), `resumeLessonId/resumeLessonTitle/lastCompletedLessonTitle`.
  - `backend/app/api/v1/routes.py`: `GET /v1/courses` (`limit` 1..50, `offset` ≥0), `CourseListOut`/`CourseListItemOut`.
  - `frontend/src/app/providers.tsx` (viết lại): `SessionProvider` (epoch), `useSessionQueryKey`, `useRequireAuth`, `useSessionRefresh`, `useRedirectAfterLogin` (chặn open redirect), `useLogout` clear cache; retry policy không retry 4xx.
  - `frontend/src/app/page.tsx`: dashboard "Khóa học của tôi" (5 gần nhất, tiến độ %, link "Học tiếp", empty/loading/error+retry).
  - `frontend/src/app/login/page.tsx`: guard-safe (`Suspense` cho `useSearchParams`), hỗ trợ `?next=`, label `htmlFor`, `role="alert"`, nút toggle `type="button"`.
  - `frontend/src/app/new/**`: route guard, session-scoped keys, interview reload logic, proposal hiển thị trạng thái `approved` và disable nút, generating phân biệt trạng thái/lỗi retryable.
  - `frontend/src/app/course/[courseId]`, `lesson/[lessonId]`: route guard, session-scoped key, invalidate `["session"]` sau khi nộp quiz.
  - `frontend/src/app/globals.css`: `.sr-only`, `.course-list`, `:focus-visible`, `prefers-reduced-motion`.
  - `frontend/src/lib/api.ts`: `fetchCourses`, type `CourseList/CourseListItem`.
  - `backend/e2e_acceptance.py`: +5 check (10, 10b, 10c, B3, B4) → **35/35**.
- TESTED:
  - `python -m pytest -q` → **84 passed, 6 skipped** (9.03s). Thêm `tests/test_courses_list.py` (6 test: scoped, pagination, param range 422, resume chuyển bài, 401, không có tham số userId).
  - `npm run build` → OK (9 routes). `npx tsc --noEmit` → không lỗi. Frontend container rebuild; `/`, `/login`, `/new`, `/course/crs_x`, `/lesson/lsn_x`, `/new/interview?courseId=crs_x` → 200.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **35/35 PASS** (10 dashboard scoped; 10b progress+resume; 10c pagination; B3 B không thấy course A; B4 B bị 404 ở generation/proposal/interview).
- NOT TESTED: browser automation thật (Playwright) cho cache isolation/login-switch; screen reader; kiểm thử mạng chập chờn trên UI; `next lint` (chưa có ESLint config, không tự tạo).
- BLOCKED: none.
- Database: không đổi schema (chỉ thêm endpoint & query), revision vẫn `0004_p12_job_reliability`.
- Security: `GET /v1/courses` bỏ qua mọi tham số `userId` (test chứng minh); guard chỉ là UX, dữ liệu vẫn 404 ở server; open-redirect chặn `//` và URL ngoài; 401 không bị retry vô hạn; không log token/cookie.
- Regressions: 0. pytest 78 → 84; E2E 30 → 35; build OK.
- Known limitations:
  - Cache isolation dựa trên TanStack Query key + `removeQueries`; nếu service worker/cache CDN được thêm sau này cần rà lại.
  - `sessionEpoch` reset khi full reload (by design — cache cũng mất theo).
  - Interview chưa cho phép sửa câu trả lời đã gửi (server không giữ bản nháp); nằm ngoài contract hiện tại.
  - Dashboard mới hiển thị 5 khóa gần nhất ở trang chủ; chưa có trang danh sách đầy đủ.
- PHASE GATE: **PASS** (A→logout→B không lộ cache; list chỉ của B; reload giữ tiến độ; build pass; E2E 35/35).
- NEXT: P2.0 LLM Provider Infrastructure (provider-neutral, mock vẫn mặc định). **ĐÃ HOÀN THÀNH** — xem entry phía trên.

## 2026-10-30 — P1.2 Reliable Generation Jobs & Safe Retries
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - State machine: `queued → running → ready`, và `running → queued` (transient, bounded) hoặc `→ failed` (fatal/hết lượt). Approve/retry giữ `queued` rồi dispatch.
  - **Outbox**: `dispatched_at IS NULL` = "DB đã commit nhưng broker chưa nhận". Reconciler (Celery beat, 30s) gửi lại; không bao giờ bỏ job kẹt `queued`.
  - **Không phải exactly-once**: claim nguyên tử đảm bảo *một worker chạy một lần tại một thời điểm*; redelivery là no-op.
  - `attempts_count` = số lần worker claim (bắt đầu 0, chặn bởi `max_attempts`=3). Không dùng để đếm retry của người dùng.
  - Inline fallback chỉ cho dev/test; compose đặt `GENERATION_ALLOW_INLINE_FALLBACK=false` cho backend/worker/beat.
- IMPLEMENTED:
  - `backend/app/services/job_service.py` (mới): `claim_job` (`UPDATE ... WHERE queued OR lease hết hạn RETURNING`), `renew_lease`, `is_superseded`, `finish_ready`, `fail_or_requeue`, `classify_error`, `retry_countdown` (backoff 2/4/8… chặn 60s), `dispatch_job` (broker + outbox ack + `dispatch_attempts`), `recover_stuck_jobs`, `_fail_exhausted`.
  - `backend/app/worker/generation.py` (viết lại): claim trước khi làm gì, heartbeat mỗi lesson, `asyncio.wait_for(provider.generate_lesson, timeout)`, chặn `SUPERSEDED`/`LEASE_LOST`, giữ `course_id` scalar sau rollback (fix MissingGreenlet), retry có backoff qua `fail_or_requeue`.
  - `backend/app/worker/reconcile.py` (mới) + `celery_app.beat_schedule`: reconciler định kỳ.
  - `backend/app/worker/celery_app.py`: `acks_late`, `prefetch=1`, time limits, `visibility_timeout`.
  - `backend/app/services/course_service.py`: `_lock_course_row` (`SELECT … FOR UPDATE` + `populate_existing`) trước khi kiểm tra state; `_active_job` chặn tạo 2 job; pin `proposal_version`; 409 `JOB_ALREADY_ACTIVE`.
  - `backend/app/api/v1/routes.py`: dispatch qua `job_service` (không raise khi broker lỗi); `GenerationOut` thêm `attempts`, `dispatched`, `lastErrorCode`.
  - `backend/alembic/versions/0004_p12_job_reliability.py` (mới, expand-only): 7 cột + index `(status, created_at)`.
  - `docker-compose.yml`: thêm service `beat`; `GENERATION_ALLOW_INLINE_FALLBACK=false` cho backend/worker/beat.
  - Frontend `new/generating`: `useMutation` retry (chống spam), label trạng thái tiếng Việt, hiển thị "đang chờ worker" khi `dispatched=false`, phân biệt lỗi retryable, dừng poll ở terminal state.
  - `.env.example`: 6 biến reliability. `e2e_acceptance.py`: +3 check (5b, 5c, 5d) → **30/30**.
- TESTED:
  - `python -m pytest -q` → **78 passed, 6 skipped** (10.04s). 6 skip = 2 file race PostgreSQL khi thiếu `POSTGRES_TEST_URL`.
  - `POSTGRES_TEST_URL=… pytest tests/test_p11_postgres_concurrency.py tests/test_p12_postgres_concurrency.py -q` → **6 passed** (3.21s): 10 worker claim đồng thời ⇒ đúng 1 thắng; 10 approve đồng thời ⇒ đúng 1 job; lease hết hạn ⇒ 1 worker claim lại; reconciler idempotent.
  - `npm run build` → OK. Frontend rebuild + `/`, `/login`, `/new/generating` → 200.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **30/30 PASS** (5b `dispatched=true attempts=1`; 5c retry tạo job mới; 5d retry không phá bài đã học).
  - **Failure injection trên Docker stack thật:**
    - *Redis down:* `docker compose stop redis` → approve vẫn **202**, job `queued` với `dispatched=false`, `attempts=0` (không báo thành công giả). `docker compose start redis` → beat phát reconciler sau ≤30s, log `reconciler recovered jobs count=1`, job → **ready** (`dispatch_attempts=2`).
    - *Worker chết:* force `lease_expires_at = now()-10min` trên job đang `running` → reconciler requeue, worker mới claim (`attempts_count=2`), sinh đủ **4 lessons**, không trùng.
    - *Duplicate delivery:* chạy task 2 lần cùng job → 4 lessons (không nhân đôi), job ready.
    - *Provider timeout / schema invalid:* unit test với provider giả → `PROVIDER_TIMEOUT` ⇒ requeue; `PROVIDER_SCHEMA_INVALID` ⇒ failed ngay; bài cũ giữ nguyên.
  - Alembic DB tạm: `0003 → 0004` (7 cột + index đúng), `downgrade -1` về `0003` (còn 10 cột), `upgrade head` lại OK, autogenerate ⇒ `pass`.
  - DB chính `ailp`: `0004_p12_job_reliability (head)`; 37 users / 28 courses / 64 lessons / 17 attempts / 18 jobs / 32 units (đã tăng do các lần chạy E2E/failure-injection — dữ liệu seed cũ 24 users vẫn còn).
- NOT TESTED: Celery broker failover nhiều node; real LLM provider cost/latency; load test nhiều job song song; `next lint` (Next 15 yêu cầu khởi tạo ESLint interactively — chưa cấu hình, không tự ý tạo config).
- BLOCKED: none.
- Database: revision `0004_p12_job_reliability`. Backup trước migration: `backup_pre_p12_20261030_234631.sql` (10 COPY, 130 KB, đã gitignore). Không xoá volume, không drop bảng.
- Security: ownership giữ nguyên (404 cross-user); lỗi provider được rút gọn ≤200 ký tự, không log prompt/key; không có endpoint nào cho client tự set `status` job; `JOB_ALREADY_ACTIVE` chặn double-approve cả ở DB lock.
- Regressions: 0. E2E 27 → 30 check, pytest 57 → 78.
- Known limitations:
  - Exactly-once vẫn không tuyệt đối (worker crash *sau* khi ghi lesson nhưng *trước* commit cuối → lần claim sau upsert lại theo `order_index`, nên không nhân bản; nhưng `lessons_done` có thể nhảy).
  - `_fail_exhausted` dùng chung `CourseStatus.failed` — chưa tách mã lỗi cấp course.
  - Reconciler là single beat instance; nhiều instance sẽ dispatch trùng (vô hại vì claim nguyên tử, nhưng tốn broker message).
  - Chưa có metric Prometheus/OTel (để P6).
- PHASE GATE: **PASS** (claim race + outbox recovery + bounded retry + no-false-success đều có bằng chứng chạy thật trên Docker; không mất dữ liệu).
- NEXT: P1.3 Frontend UX, Navigation & Session Isolation. **ĐÃ HOÀN THÀNH** — xem entry phía trên.

## 2026-10-30 — P1.1 Quiz Integrity, Progress, XP & Content Versioning
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - **PROPOSAL (policy mới)**: lesson `completed` khi có attempt đạt **≥80%** trên `contentVersion` hiện hành (`lesson_content.COMPLETION_THRESHOLD_PERCENT = 80`). Không đồng nhất `LessonStatus.ready` với "đã học".
  - **PROPOSAL (XP)**: XP tính theo `(user, lesson, contentVersion)` với mức thưởng tối đa; nộp lại/retry chỉ nhận phần chênh lệch, tổng không vượt mức tối đa ⇒ không farm XP. Sinh lại nội dung (version mới) cho phép nhận XP cho version mới.
  - **PROPOSAL (post-submit)**: `GET lesson` không bao giờ trả đáp án; response nộp bài có `results[i].solution` (đáp án) để UI hiển thị sau khi nộp.
- IMPLEMENTED:
  - `backend/app/services/lesson_content.py` (mới): public projection (loại `answerIndex`/`answer`/`acceptedAnswers`/`pairs`), shuffle ổn định theo `sha256(lessonId:contentVersion:blockId)` cho order/match + id public, grading deterministic dùng id public, `solution_for`, `is_completed`.
  - `backend/app/services/grading_service.py`: **xoá** — thay bằng `lesson_content` (một nguồn chấm duy nhất, không còn hai logic lệch nhau).
  - `backend/app/services/lesson_service.py`: ownership bằng JOIN `courses.user_id`; validate duplicate index + index ngoài bounds (422); `SELECT users.xp ... FOR UPDATE` để tuần tự hoá XP; idempotency theo `(lesson,user,clientAttemptId)` + bắt `IntegrityError` khi race; ghi `attempt.xp_awarded`; XP không vượt mức tối đa cho version.
  - `backend/app/api/v1/routes.py`: GET lesson trả `public_blocks`; attempt trả `xpEarned = attempt.xp_awarded` (không tính lại từ score); course detail nhận `user_id`.
  - `backend/app/services/course_service.py`: `_completed_lesson_ids()` tính progress từ attempts của version hiện hành; `get_course_detail` trả `progress` + `lessons[].completed`; `approve_course` set `proposal.approved_at`.
  - `backend/app/models/models.py`: `LessonAttempt.xp_awarded`, `XpEvent.content_version`, index `ix_xp_events_lesson_version`.
  - `backend/alembic/versions/0003_p11_quiz_integrity.py` (mới, expand-only): 2 cột + 1 index, idempotent theo inspector; downgrade drop đúng phần thêm.
  - `backend/app/schemas/schemas.py`: `LessonSummaryOut.completed`, `AttemptResultOut.solution`, `AttemptAnswer` `extra=forbid` + từ chối `answer` kiểu bool (chặn coerce `true`→`1`).
  - `backend/app/worker/generation.py`: chỉ tăng `content_version` khi title/nội dung **thực sự** đổi (so sánh qua chữ ký JSON để tuple/list không gây bump giả); `except Exception`.
  - Frontend `frontend/src/app/lesson/[lessonId]/page.tsx`: viết lại cho public blocks (order/match dùng id), `clientAttemptId` ổn định theo fingerprint nội dung (retry mạng không tạo attempt mới), `useMutation` + invalidate `["course"]`/`["me"]`, loading/error/retry, aria-label cho nút điều hướng.
  - Frontend `frontend/src/app/course/[courseId]/page.tsx`: hiển thị tiến độ %, badge "✓ đã học", loading/error/retry.
  - `backend/e2e_acceptance.py`: dựng đáp án từ **private content trong DB** (`E2E_PG_DSN`, không đọc public payload) + 6 check mới (7b, 8c, 8d, 9b, 9c, 9d) → **27/27**.
- TESTED:
  - `python -m pytest -q` (backend) → **57 passed, 2 skipped** (6.48s). 2 skip = test race PostgreSQL khi thiếu `POSTGRES_TEST_URL`.
  - `POSTGRES_TEST_URL=...p11_race_check python -m pytest tests/test_p11_postgres_concurrency.py -q` → **2 passed** (1.07s): 20 request đồng thời cùng `clientAttemptId` ⇒ 1 attempt, XP = 70 đúng 1 lần; 20 request với id khác nhau ⇒ 20 attempt nhưng XP vẫn 70.
  - `npm run build` → OK, 9 routes. Frontend container rebuild + `GET /lesson/...`, `/course/...`, `/login` → 200.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` (Docker stack, code mới) → **27/27 PASS**: gồm `7b GET lesson không lộ answer key`, `8c nộp lại không farm XP`, `8d client gửi correct=true → 422`, `9b progress từ attempt 25%`, `9c lesson được đánh dấu`, `9d stale version → 409`.
  - Alembic trên DB tạm `g0_fresh_verify`: `0002 → 0003` (2 cột + index đúng), `downgrade -1` về `0002` (cột biến mất), `upgrade head` lại OK; `alembic revision --autogenerate` ⇒ `pass` (không drift).
- NOT TESTED: LLM thật (không có key); browser automation (Playwright) cho UI; load test.
- BLOCKED: none.
- Database: revision `0003_p11_quiz_integrity` đã áp dụng trên DB chính `ailp`. Backup trước migration: `backup_pre_p11_20261030_231407.sql` (10 COPY, 107 KB). Sau migration: 24 users / 32 lessons / 6 attempts **giữ nguyên**. Downgrade path: drop 1 index + 2 cột (rows cũ `xp_awarded=0`, `content_version=NULL`); không backfill vì không tái dựng được XP lịch sử chính xác.
- Security: answer key không rời server trước khi nộp (test cả 5 loại block); client không thể gửi `correct`/field lạ (422) hay bool; ownership vẫn 404 ở course + lesson; XP dưới row lock; `solution` chỉ có trong response POST attempts.
- Regressions: E2E cũ vẫn pass (21 → 27 check, 0 fail); pytest 40 → 57 (+17); build OK.
- Known limitations:
  - `GET /v1/courses/{id}` giờ chạy thêm 1 query attempts (nhỏ, có index `(lesson_id,user_id)` sẵn có); có thể gộp aggregate sau.
  - Progress threshold 80% là PROPOSAL chưa được người dùng duyệt riêng — đổi qua hằng số `COMPLETION_THRESHOLD_PERCENT`.
  - `xp_events.content_version` NULL cho rows lịch sử (trước 0003) ⇒ các attempt cũ không được tính vào "XP đã cộng theo version" (chỉ ảnh hưởng nếu user nộp lại bài cũ sau khi có version tăng; hành vi an toàn: cộng thêm tối đa 1 lần).
  - Chưa có endpoint danh sách attempts (chỉ dùng nội bộ).
- PHASE GATE: **PASS** (6/6 acceptance criteria có bằng chứng chạy thật; race test trên PostgreSQL pass; không mất dữ liệu).
- NEXT: P1.2 Reliable Generation Jobs & Safe Retries.

## 2026-10-30 — G0 Audit, Quality Gate & Migration Consistency
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`, HEAD == baseline, không có commit mới)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions: re-audit baseline, chạy lại toàn bộ test/build/E2E, kiểm tra revision Alembic trên **DB tạm**, rà code course/lesson/worker/provider để chốt backlog P1.1/P1.2. Không sửa `0001_initial.py` / `0002_auth_columns.py`.
- IMPLEMENTED:
  - `backend/alembic/env.py`: import `app.models` để `Base.metadata` có bảng thật. **Trước fix:** `alembic revision --autogenerate` trên DB vừa upgrade head sinh migration **drop toàn bộ 9 bảng** vì metadata rỗng (đã kiểm chứng bằng file autogen rồi xoá). **Sau fix:** autogenerate sinh `upgrade(): pass` (no drift). Không đổi revision nào.
- TESTED (môi trường: Windows, Python 3.13.7, Docker Compose stack đang chạy, PostgreSQL 16):
  - `python -m pytest -q` (backend) → **40 passed, 8 warnings, 3.01s** (exit 0). Cảnh báo: httpx per-request cookies deprecated; `HTTP_422_UNPROCESSABLE_ENTITY` deprecated alias.
  - `npm run build` (frontend) → **thành công**, 9 routes (`/`, `/login`, `/new*`, `/course/[courseId]`, `/lesson/[lessonId]`).
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **21/21 PASS** (auth, CSRF 403, unauth 401, cross-user 404, generate 4 lessons, quiz 5/5, reload, token giả 401).
  - Docker: `docker compose ps` → 5/5 service chạy; `/health` → `{"status":"ok","env":"development","provider":"mock"}`.
  - Alembic trên **DB tạm `g0_revision_verify`** (tạo mới trong container `db`, port host 5433; **không đụng `ailp`**):
    - `alembic upgrade head` → `0002_auth_columns (head)`; 9 bảng + `alembic_version`; `users` = 10 cột, `email`/`password_hash` nullable.
    - `alembic downgrade -1` → `0001_initial`; `users` còn 8 cột (mất đúng 2 cột auth) và chỉ còn `users_external_id_key`.
    - `alembic downgrade base` → chỉ còn `alembic_version`, 0 enum type còn lại (downgrade xoá enum sạch).
    - `alembic upgrade head` lần 2 → `0002_auth_columns (head)` (forward recovery OK). DB tạm đã DROP sau kiểm tra.
  - DB chính `ailp` sau audit: `alembic_version = 0002_auth_columns`; 24 users / 20 courses / 32 lessons / 6 attempts — **không thay đổi dữ liệu**.
- NOT TESTED: backup/restore drill (P6); real LLM (không có key, ngoài scope G0); browser-based UI test.
- BLOCKED: none.
- Database: không tạo revision mới. Phát hiện lệch **không phá dữ liệu** trên DB fresh: 0001 tạo `users_email_key` (unique trên `email`) và 0002 tạo thêm `uq_users_email` → **2 unique constraint trùng chức năng** trên DB tạo mới hoàn toàn; DB chính chỉ có `uq_users_email` (vì 0001 được stamp, không chạy). Đề xuất forward-only (revision mới drop constraint thừa) khi thực sự cần — chưa làm trong G0 vì không ảnh hưởng correctness.
- Security: audit xác nhận GET lesson hiện trả **raw answer key** (`mc.answerIndex`, `blank.answer`, `short.acceptedAnswers`, thứ tự `order.items`, `match.pairs`) → chuyển thành gate bắt buộc của P1.1. Ownership course/lesson enforce ở server (cross-user 404 đã test).
- Regressions: không có (40/40, build OK, 21/21).
- Known limitations (chuyển P1.1/P1.2):
  - P1.1: progress luôn `0` và có nhánh chết `if lesson.status.value == "ready": pass` (`course_service.get_course_detail`); XP cộng mỗi attempt mới (farm được) và response tính lại `xpEarned` từ score thay vì giá trị đã ghi; idempotency attempt là check-then-insert (race → có thể IntegrityError/XP 2 lần); `CourseProposal.approved_at` không bao giờ được set khi approve; order/match dùng chính thứ tự mảng làm đáp án.
  - P1.2: không có atomic claim (`job.status in (ready,)` only, không khoá `queued`); `dispatch_generation` chạy sau `commit` và không bắt lỗi `send_task` → job kẹt `queued`; `_use_celery` chọn lúc import; `except (SchemaInvalidError, Exception)`; không retry/backoff/heartbeat; `attempts_count` chỉ tăng ở `retry_course`.
- PHASE GATE: **PASS** (baseline tái lập được; schema/revision kiểm chứng trên DB tạm; không tác động dữ liệu chính; nguy cơ migration được ghi nhận là known limitation, không cần rollback).
- NEXT: P1.1 Quiz Integrity + Progress + XP + Content Version.

## 2026-10-30 (buổi 3) — P0.5.1 Auth & Migration Stabilization

### Sửa lỗi + hardening
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Hằng số HTTP sai `HTTP_422_UNAUTHORIZED` → `HTTP_422_UNPROCESSABLE_ENTITY` | IMPLEMENTED + TESTED | user_service.py; test_invalid_email_returns_422_not_401 (422 + không có WWW-Authenticate header) |
| **Bug rate limit dead-code:** `bucket.append(now)` nằm trong nhánh `if` sau `raise` → request hợp lệ không bao giờ được ghi bucket → rate limit không bao giờ block | IMPLEMENTED + TESTED | limits.py fix; test_login_rate_limited: 10× 401 rồi lần 11 → 429; test_register_rate_limited tương tự |
| Rate limit cho /auth/login (10/phút), /auth/register (10/phút), /auth/logout (30/phút) | IMPLEMENTED + TESTED | auth.py; 2 test trên |
| Rate-limit buckets clear giữa tests (fixture) | IMPLEMENTED + TESTED | conftest.py client fixture; test_rate_limit_buckets_reset_between_tests → 401 (không 429) |
| Auth resolution: deleted user + token hợp lệ → 401 USER_NOT_FOUND (không crash) | TESTED | test_valid_token_with_deleted_user_returns_401 |
| User scope trong session: /me trả đúng user đăng nhập, không leak giữa users | TESTED | test_me_after_login_same_user_no_crossuser_leak |

### Kiểm chứng migration/rollback (không đụng dữ liệu chính)
| Kiểm chứng | Kết quả |
|---|---|
| SQLite: upgrade head → downgrade base → upgrade head → current | 0002_auth_columns (head) — pass |
| PostgreSQL **temp DB riêng** `alembic_verify_tmp` (trong container db, KHÔNG phải DB chính): upgrade head → \d users có email+password_hash+uq_users_email → downgrade base → chỉ còn alembic_version | pass; temp DB đã DROP sau verify |
| DB chính `ailp`: 20 users giữ nguyên, không volume bị xóa | XÁC MINH sau verify |

### Regression P0.5.1 (Docker stack, code mới)
1. `pytest -q` → **40/40 passed** (33 cũ + 7 mới).
2. `npm run build` → ✓ Compiled successfully, 9 static pages.
3. `docker compose up -d --build backend worker` → started; `/health` → ok.
4. `e2e_acceptance.py` → **21/21 PASS**.

### Ràng buộc đã tôn trọng
- Migration 0001/0002 đã deploy **không bị sửa hash/content** — chỉ verify.
- Không xóa volume `reverseengineer_pgdata`, không mất dữ liệu (backup vẫn còn từ P0.5).
- Không tích hợp LLM thật / Tutor / RAG.

### Giới hạn còn lại
- Rate limit vẫn in-memory per-process (restart mất bucket) — distributed Redis để sau.
- `HTTP_422_UNPROCESSABLE_ENTITY` là deprecated alias trong Starlette mới (vẫn hoạt động); cân nhắc đổi sang `HTTP_422_UNPROCESSABLE_CONTENT` khi bump dependency.
- WEAK_PASSWORD của service layer hiện không thể trigger qua HTTP (Pydantic schema chặn trước với cùng điều kiện) — được test trực tiếp ở service level.

---

## 2026-10-30 (buổi 2) — P0.5 Authentication + Alembic Migration

### Backend — Auth (JWT HttpOnly cookie + Argon2id + CSRF)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| POST /v1/auth/register, /login, /logout, GET /me | IMPLEMENTED + TESTED | E2E steps 0, 0b, 0d pass; pytest test_auth.py 13/13 |
| Argon2id password hashing (không plaintext) | IMPLEMENTED + TESTED | test_register_login_me_flow assert `$argon2id$` prefix |
| JWT HS256 + iss/aud/exp validation, secret server-side only | IMPLEMENTED + TESTED | test_expired_token_rejected, test_wrong_issuer_or_audience_rejected, test_tampered_token_rejected |
| get_current_user dependency (user ID từ token, không từ client header) | IMPLEMENTED + TESTED | test_fake_x_user_id_header_does_not_authenticate → 401 |
| X-User-Id demo header chỉ khi ALLOW_DEMO_HEADER=true + ENV=development | IMPLEMENTED + TESTED | compose default false; pytest chạy với false |
| CSRF double-submit cho mutating requests | IMPLEMENTED + TESTED | test_csrf_missing_on_mutation_403; E2E step 0d → 403 |
| Cross-user access → 404 | IMPLEMENTED + TESTED | test_cross_user_access_denied; E2E B/B2 → 404 |
| Ownership + luồng học sau login/reload | IMPLEMENTED + TESTED | test_login_reload_and_continue; E2E step 9 pass |

### Backend — Alembic
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Alembic setup (env.py sync driver, alembic.ini) | IMPLEMENTED + TESTED | `alembic upgrade head` SQLite: 9 bảng tạo thành công |
| Migration 0001_initial (full schema, viết tay khớp models) | IMPLEMENTED + TESTED | upgrade head + downgrade base sạch (SQLite) |
| Migration 0002_auth_columns (idempotent, batch mode cho SQLite) | IMPLEMENTED + TESTED | cycle upgrade→downgrade→upgrade pass; chạy thật trên PostgreSQL DB cũ |
| Backend container chạy `alembic upgrade head` trước start | IMPLEMENTED + TESTED | Dockerfile CMD; logs không lỗi DuplicateTable sau rebuild |
| create_all chỉ còn cho SQLite (dev/test) | IMPLEMENTED + TESTED | pytest 33/33 vẫn pass |
| Migration DB cũ không mất dữ liệu | IMPLEMENTED + TESTED | backup `backup_pre_migration_20261030_221411.sql`; stamp 0001 + upgrade → 16 users + 16 courses giữ nguyên; runbook `docs/migration-runbook.md` |

### Frontend
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| /login page (đăng nhập + đăng ký, toggle mode) | IMPLEMENTED + TESTED | `npm run build` pass; HTTP 200 trên Docker |
| Session bằng HttpOnly cookie (KHÔNG lưu token localStorage) | IMPLEMENTED + TESTED | api.ts `credentials: "include"`; không còn getUserId() |
| CSRF header tự gửi từ csrf_token cookie | IMPLEMENTED + TESTED | api.ts getCsrfToken(); E2E 21/21 pass |
| useAuth + AuthBar (hiển thị user + XP + logout) | IMPLEMENTED | providers.tsx |
| Trang chủ yêu cầu đăng nhập trước khi tạo course | IMPLEMENTED | page.tsx render /login link khi chưa auth |

### Kiểm chứng chạy thật (2026-10-30, Docker Compose full stack)
1. `pytest -q` → **33/33 passed** (20 cũ viết lại cho auth + 13 auth mới).
2. `npm run build` → **thành công** (9 routes, có /login).
3. `docker compose up --build -d` → 5/5 containers Up (db healthy, redis healthy).
4. `python e2e_acceptance.py` → **21/21 PASS** (đã cập nhật: đăng ký/đăng nhập, CSRF, unauth 401, token giả 401, cross-user 404, generation + quiz + reload).
5. Worker: `Task ... succeeded in 0.54s`, 0 Traceback.
6. DB xác minh: users có `password_hash` (argon2id), attempts + xp_events được ghi; dữ liệu cũ 16 users/16 courses giữ nguyên sau migration.

### Các lỗi đã gặp và sửa trong P0.5
1. Alembic CLI autogenerate không chạy được với URL async + greenlet → viết migration tay từ `Base.metadata` (render qua autogenerate API).
2. Migration 0002 duplicate column trên DB mới → chuyển sang idempotent check bằng SQLAlchemy inspector.
3. SQLite không hỗ trợ ALTER ADD/DROP CONSTRAINT → `batch_alter_table` (copy-and-move) khi dialect là sqlite.
4. httpx cookie per-request deprecated warnings — không ảnh hưởng kết quả.
5. Image cũ không chứa 0002 (build trước khi tạo file) → rebuild backend rồi upgrade.

### Chưa làm / giới hạn (cập nhật)
| Thành phần | Trạng thái |
|---|---|
| AI Tutor (SSE, tool registry, allowance) | NOT IMPLEMENTED — thiết kế trong architecture.md |
| RAG Engine (pgvector, citations) | NOT IMPLEMENTED — schema预留 trong database-design.md |
| Gamification nâng cao (streak/hearts/goal/levels) | NOT IMPLEMENTED — chỉ XP cơ bản |
| Refresh token / token rotation | NOT IMPLEMENTED — access token TTL 7 ngày, đủ cho slice hiện tại |
| Adapter LLM thật (OpenAI/Anthropic/...) | NOT IMPLEMENTED — interface sẵn sàng, key qua env |
| Rate limit distributed (Redis) | NOT IMPLEMENTED — in-memory per-process, identity theo user id |
| HTTPS/deploy production | NOT IMPLEMENTED — local only (COOKIE_SECURE cần bật khi có HTTPS) |

### Khẳng định đúng mức
- Mock provider **KHÔNG phải AI thật** — nội dung sinh theo template deterministic.
- Token hết hạn sẽ bị từ chối (TESTED); chưa có refresh flow — user đăng nhập lại khi hết hạn.
- Chưa kiểm chứng security ở mức pen-test — chỉ các test case tự viết.

---

## 2026-10-30 — Slice 0 + Slice 1 hoàn thành

### Backend (FastAPI + SQLAlchemy async + Celery)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| API: courses/interview/proposal/approve/generation/retry | IMPLEMENTED + TESTED | E2E 16/16 pass qua HTTP thật |
| API: lessons/attempts (grading server-side) | IMPLEMENTED + TESTED | Quiz 5/5 đúng; duplicate attempt idempotent |
| MockProvider (interview questions, proposal, lessons) | IMPLEMENTED + TESTED | Deterministic; schema validate Pydantic |
| Grading deterministic (mc/blank/order/match/short) | IMPLEMENTED + TESTED | Unit tests 9 case |
| Celery worker generation task | IMPLEMENTED + TESTED | Worker log: `Task ... succeeded in 0.11s`; 0 Traceback |
| Idempotency: course + attempt | IMPLEMENTED + TESTED | `test_duplicate_course_creation_idempotent`, `8b. Attempt idempotent` |
| Ownership check (course/lesson) | IMPLEMENTED + TESTED | User khác truy cập → 404 |
| Rate limit in-memory per-process | IMPLEMENTED + TESTED | 429 khi vượt ngưỡng (unit) |
| XP cơ bản | IMPLEMENTED + TESTED | xpEarned=70 cho 5/5 đúng (50 + 20 bonus) |
| Generation retry (upsert không trùng lesson) | IMPLEMENTED + TESTED | retry → 4 lessons unique |

### Frontend (Next.js 15 + TanStack Query)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Pages: /, /new, /new/interview, /new/proposal, /new/generating, /course/[id], /lesson/[id] | IMPLEMENTED | `npm run build` thành công, 8 routes |
| Poll generation 2s tự dừng khi ready/failed | IMPLEMENTED | refetchInterval logic |
| Quiz player 5 loại block | IMPLEMENTED | render + nộp + hiển thị kết quả/đáp án |
| Lưu userId localStorage (persistent identity) | IMPLEMENTED | reload giữ user |

### Kiểm chứng chạy thật (2026-10-30)
1. **Unit + integration tests:** `pytest tests` → **20/20 passed** (backend, SQLite in-memory).
2. **E2E local uvicorn:** `e2e_acceptance.py` → **16/16 PASS** (SQLite + inline fallback).
3. **E2E Docker Compose full stack:** `e2e_acceptance.py` → **16/16 PASS** (PostgreSQL + Redis + Celery worker thật; xác minh qua `docker compose logs worker` và query trực tiếp trong `db` container — courses/lessons/attempts/users/xp đều tồn tại trong PostgreSQL).
4. **Frontend build:** `npm run build` → thành công, serve tại :3000 (HTTP 200).
5. **Retry flow:** approve → ready → retry → job mới chạy → lessons upsert không trùng (4 unique).
6. **Cross-ownership:** user B truy cập course/lesson của user A → 404 (course + lesson).

### Các lỗi đã gặp và sửa trong quá trình
1. UUID parse lỗi vì id có prefix `crs_`/`lsn_` → thêm `parse_prefixed_uuid`.
2. SQLite in-memory mất bảng giữa các connection → `StaticPool`.
3. `asyncio.run()` trong running loop (FastAPI request) → `asyncio.create_task` fallback.
4. Pydantic union blocks không phân biệt theo `type` → `Annotated[..., Field(discriminator="type")]`.
5. SQLAlchemy relationships thiếu (`Course.units`, `Unit.lessons`) cho `selectinload`.
6. **asyncpg cross-loop:** Celery task dùng engine module-level → `RuntimeError: ... attached to a different loop` / `InterfaceError: another operation is in progress` → worker tạo engine riêng mỗi task, dispose sau. (Lỗi này đã xác minh: trước fix worker fail, sau fix `succeeded`.)
7. Celery CLI không nhận `:get_celery_app` function → tạo module `app.worker.celery_app.py`.
8. Windows host: `localhost:8001` trỏ IPv6 `[::1]` timeout 8s/conn → dùng `127.0.0.1`. (Môi trường, không phải bug app.)

### Chưa làm / giới hạn
| Thành phần | Trạng thái |
|---|---|
| AI Tutor (SSE, tool registry, allowance) | NOT IMPLEMENTED — thiết kế trong architecture.md |
| RAG Engine (pgvector, citations) | NOT IMPLEMENTED — schema预留 trong database-design.md |
| Gamification nâng cao (streak/hearts/goal/levels) | NOT IMPLEMENTED — chỉ XP cơ bản |
| Auth JWT/OAuth | NOT IMPLEMENTED — demo user qua header `X-User-Id` |
| Adapter LLM thật (OpenAI/Anthropic/...) | NOT IMPLEMENTED — interface sẵn sàng, key qua env |
| Alembic migration | NOT IMPLEMENTED — dùng `create_all` (đủ cho slice này; migration cần khi schema ổn định) |
| Content versioning nâng cao (regenerate giữ attempts) | NOT IMPLEMENTED — contentVersion đã có trong schema |
| Rate limit distributed (Redis) | NOT IMPLEMENTED — in-memory per-process |
| HTTPS/deploy production | NOT IMPLEMENTED — local only |

### Khẳng định đúng mức
- Mock provider **KHÔNG phải AI thật** — nội dung sinh theo template deterministic. Nhãn "AI" chỉ đúng khi bật adapter thật.
- Không kiểm chứng giả thuyết RAG hay thuật toán backend của hệ thống được phân tích — chỉ tham khảo hình thái nghiệp vụ (interview 5 câu, proposal, poll generation, batch attempts) từ 2 báo cáo REA.
