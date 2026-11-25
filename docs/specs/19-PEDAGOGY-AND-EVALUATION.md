# 19 — Learning Design, DAG Curriculum & AI Evaluation Specification

**Trạng thái (`2026-11-22`):** **P2.1 (DAG + `LearnerProfile`)**, **P2.2 (12-topic eval harness + rubric + cost tracking)** và **`P1-PEDAGOGY`** (fix parser tiếng Việt không dấu/đơn vị) đã **IMPLEMENTED · REPORTED TESTED**. Kết quả eval thực tế đầu tiên đạt **3.17/4** và đã khoanh vùng chính xác các lỗi cần sửa ở Wave 2 (`P1-CONTENT-TRUNC`, `P1-LANG`, `P1-LEVEL-FIT`).

## 1. Learning objectives & DAG validation (IMPLEMENTED — P2.1)

- Dùng **Bloom's Taxonomy** (`remember`, `understand`, `apply`, `analyze`, `evaluate`, `create`) trên từng `CurriculumSkill`.
- `ProposalPayload` chứa `learnerProfile`, `skills[]` (tối đa 48), `prerequisites[]` (tối đa 96 cạnh `[prereqId, skillId]`).
- **Invariants đã cài & kiểm thử (`test_p21_pedagogy.py`):**
  1. Skill IDs unique, title không rỗng, mapping lesson khớp `lessonTitles`.
  2. Edge endpoints tồn tại, không self-loop, đồ thị **acyclic** (reject cycle trước approve/generate).
  3. Beginner graph không bắt buộc phải có cạnh; legacy proposals không có `skills` vẫn đọc được.
- **Cập nhật `P1-PEDAGOGY` (`2026-11-05`, uncommitted):** chuẩn hóa bỏ dấu tiếng Việt (`_fold()`), word boundary lookaround, sửa parser thời lượng (`gio`/`phut`/`tieng`), độ sâu (`hiểu sâu` + cảnh báo xung đột `deep`/`broad`) và phong cách (`đồ thị`, `ví dụ thực tế`) — 54 tests pass (`tests/test_p1_pedagogy.py`).

## 2. Evaluation harness & Baseline thực tế (`P2.2`, `2026-11-04`)

- **Harness:** `backend/evals/` (`p22_real_eval.log`, `docs/audits/polyskill-parity-2026-11-04/08-ai-quality-evaluation.md`).
- **Baseline đã đo trên provider thật (`openai_compatible`, `deepseek-ai/deepseek-v4.1-flash-1017`, prompt `p3.0-v1`):**
  - 12 topics, 149 LLM calls, **`N = 11` scored** (1 topic chạm `PROVIDER_BUDGET_EXCEEDED`).
  - **Mean: `3.17 / 4`** (median `3.22`, min `2.67`, max `3.56`, stdev `0.315`).
  - Tiêu chí cao nhất: `safety` (`4.000`), `repetition` (`3.727`).
  - Tiêu chí thấp nhất: **`language_quality` (`2.273`)**, **`level_fit` (`2.364`)**, **`answer_consistency` (`2.818`)**.
  - **Lỗi lặp lại phát hiện được:**
    1. **Truncation (`P1-CONTENT-TRUNC`):** `7/11` topic bị cắt cụt ở trần output token — **OPEN**.
    2. **Language mismatch (`P1-LANG`):** `6/6` topic tiếng Anh bị trả tiếng Việt do chưa có tham số ngôn ngữ — **OPEN**.
    3. **Level mismatch (`P1-LEVEL-FIT`):** `8/11` topic lệch trình độ so với yêu cầu — **OPEN**.
    4. **Multi-blank ambiguity (`P1-QUIZ-BLANK`):** `5/11` topic có 2 chỗ trống / 1 đáp án — **FIXED IN CODE (`BLANK_SLOT_COUNT=1`), chưa đo lại bằng real LLM**.
  - **Bài học quan trọng:** bộ structural validation pass `12/12` trên chính tập đầu ra này ⇒ *valid JSON ≠ nội dung dạy tốt*.
  - **Chưa đo (`UNMEASURED`):** tutor scaffolding (`TUTOR_ENABLED=false`) và citation/abstention trên dữ liệu thật (`RAG_ENABLED=false`).

## 3. Rubric đánh giá (0–4 theo judge harness & review người)

- Các chiều cốt lõi: Alignment với outcomes, Progression theo DAG, Factual accuracy, `level_fit`, `language_quality`, `answer_consistency` / Quiz quality, `repetition`, `safety`.
- **Nguyên tắc bắt buộc:** *"Điểm do LLM chấm chỉ là tín hiệu tham khảo, không phải ground truth và không thay thế người chấm."* Mọi báo cáo eval phải ghi rõ `n`, failed cases, prompt/model version, token/latency/cost (hoặc `costKnown=false`), và mẫu human review.

## 4. Target gate cho đợt Re-eval tiếp theo (Wave 2 — cần duyệt ngân sách)

1. Đóng toàn bộ 3 lỗi mở: `P1-CONTENT-TRUNC`, `P1-LANG`, `P1-LEVEL-FIT` (cộng `P1-QUIZ-BLANK` & `P1-PEDAGOGY` đã xong).
2. Deterministic gate đạt 100% trên toàn bộ 12 topic fixtures (0 truncation, 0 multi-blank, 0 answer-key leak, 0 DAG cycle).
3. Real-provider re-eval (sau khi owner duyệt ngân sách) hướng tới `language_quality ≥ 3.0/4`, `level_fit ≥ 3.0/4`, `0` lỗi truncation và không hồi quy `safety`/`answer_consistency`.
4. Sau khi bật `TUTOR_ENABLED` và `RAG_ENABLED` ở môi trường đánh giá, bổ sung 2 trục đang `UNMEASURED`: tutor scaffolding và citation groundedness/abstention.

## 5. Không làm

Không coi điểm LLM-as-judge là ground truth; không gọi `MockProvider` là kết quả chất lượng sư phạm; không chạy real-provider eval khi chưa được duyệt ngân sách; không diễn giải nghiên cứu học thuật thành cam kết hiệu quả điểm số của SopiSkill.
