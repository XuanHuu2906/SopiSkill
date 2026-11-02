# 12 — Learner Profile, Skill Mastery, FSRS & Conditional ML

**Trạng thái:** **PROPOSAL / P5**; không được mô tả như adaptive AI đã triển khai.

## 1. Core principle

Cá nhân hóa giai đoạn đầu dựa trên **5 câu interview, mục tiêu và kết quả quiz**; sau khi có đủ lịch sử mới ước lượng mastery và lên kế hoạch ôn tập. Không suy ra năng lực thực chỉ từ tự khai và không hứa có deep learning nếu chỉ dùng rules.

## 2. Requirements

| ID | Description | Gate |
|---|---|---|
| ADAPT-001 | Skill IDs ổn định, lesson map vào outcomes + prereqs | Graph validated |
| ADAPT-002 | Mastery baseline rule-based từ attempts theo skill/version | Reproducible rules |
| ADAPT-003 | Gợi ý bài tiếp theo khi prerequisites đạt | Explainable recommendation |
| ADAPT-004 | FSRS dựa trên review events có rating/timezone | Deterministic schedule tests |
| ADAPT-005 | User biết lý do được gợi ý và có thể skip | UX review |
| ADAPT-006 | BKT chỉ khi có dataset đủ và vượt baseline (research-only 2026-11-02: hạ tầng đo xong, dữ liệu chưa đủ) | Held-out calibration |
| ADAPT-007 | LSTM/DKT/contextual bandit chỉ nghiên cứu, rollout có kiểm soát | Proof of value + privacy |

## 3. Rule-based baseline (P5.0 proposed)

- Mỗi skill có stable ID, prerequisites DAG không chu trình, lesson liên kết skills/outcomes.
- Estimate ban đầu từ các attempt đúng/sai và contentVersion hiện hành, có min-evidence threshold; chưa đủ dữ liệu → `unknown`, không gán giả mastery cao.
- Next lesson: thuộc course user, chưa hoàn thành, prerequisites đạt theo policy; sort theo curriculum order, có giải thích “đã hoàn thành X, cần học Y trước Z”.
- User có thể học không theo gợi ý nếu product policy cho phép; không tự khóa course do model dự đoán.

## 4. Spaced repetition FSRS (P5.0 proposed)

- Chỉ bật khi có user review event (`skillId`, `lessonId?`, `rating`, `reviewedAt`, `schedulerVersion`, `nextDueAt`).
- Tính thời gian theo timezone được chọn; lưu UTC, schedule version để tái tạo; tính lại lịch khi content/skill version thay đổi có chính sách rõ.
- Không tự suy tạo review rating từ quiz cũ nếu không được product duyệt.

## 5. Statistical models (conditional)

- **BKT:** yêu cầu chuỗi event user-skill-timestamp-correct đủ dài, train/test split theo user hoặc thời gian tránh leakage, calibration (Brier/log loss), fairness review, shadow mode.
  - **Trạng thái 2026-11-02 — RESEARCH-ONLY:** đã cài `backend/app/services/bkt.py`
    (thuần Python, 4 tham số, mục tiêu mềm `score_correct/score_total`), extractor
    read-only `backend/evals/mastery_dataset.py`, harness `backend/evals/bkt_eval.py`
    (Brier/log loss/AUC/ECE/drift/leakage, baseline as-of). **Không** thay mastery
    runtime: API vẫn trả `method="rule_based"`.
  - Dữ liệu thật 2026-11-02: 127 attempt nhưng chỉ 37 đúng `contentVersion`, 21 user,
    **0 chuỗi ≥5 event** ⇒ kết quả `INSUFFICIENT_DATA`; deploy **BLOCKED**.
    Chi tiết: `docs/specs/23-P51-BKT.md`.
- **DKT/LSTM, bandit:** chỉ khi baseline/BKT không đủ và dataset đủ; reward/bias rõ, offline evaluation và rollback trước online experimentation.
- Không tự đưa K-Means, XGBoost, full RL vào kiến trúc chỉ vì phổ biến.

## 6. Acceptance

- Rule-based recommendation deterministic, cùng history cho cùng suggestion; thiếu dữ liệu có lý do unknown.
- ContentVersion update không làm lộ attempt user khác; cross-owner course/skill history chặn.
- FSRS timezone boundary, missed reviews, duplicate events, reset schedule tested.
- Chỉ chuyển phase ML khi báo cáo eval held-out chứng minh hơn baseline; không có data → NOT STARTED.
