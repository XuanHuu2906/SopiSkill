# P5.1 — Bayesian Knowledge Tracing (research-only) — Design

**Ngày:** 2026-11-02 · **Phase:** P5.1 · **Trạng thái:** DRAFT chờ duyệt
**Branch dự kiến:** `feat/p5.1-bkt-research` (tách từ `feat/p5.0-learner-profile`)
**Quyết định người dùng:** research-only offline; **KHÔNG** bật BKT thay mastery
rule-based trong API/learning-path ở phase này.

---

## 1. Ý định và lý do

Mastery hiện tại (P5.0) là **heuristic accuracy có trọng số thời gian**. P5.1 đặt câu hỏi:
một mô hình xác suất thật (Bayesian Knowledge Tracing) có dự đoán **điểm bài kế tiếp**
tốt hơn baseline đó **trên dữ liệu của chúng ta** hay không?

Gate của `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` mục 18 rất rõ:

- cần chuỗi `(user, skill, timestamp, correct)` đủ dài, split train/test **theo user và
  theo thời gian** để tránh leakage;
- chỉ deploy khi vượt baseline **trên held-out** với calibration (Brier/log loss),
  drift và fairness review;
- chưa đủ dữ liệu ⇒ `NOT STARTED`, **không cố triển khai**.

Vì vậy P5.1 ở đây là **nghiên cứu + đo lường offline**, không thay đổi runtime:
không route mới, không feature flag runtime, không migration, không đổi `method="rule_based"`
mà API mastery đang trả.

## 2. Dữ liệu hiện có (FACT, đo 2026-11-02 trên container `db`)

| Đo | Giá trị |
|---|---|
| `alembic_version` | `0012_p41_rag` (P5.0 **chưa apply** trên DB dev này) |
| `lesson_attempts` | 127 |
| user có attempt | 66 |
| user có ≥ 2 attempt | 60 |
| user có ≥ 5 attempt | **0** (max = 3) |
| attempt đúng `contentVersion` hiện hành | 37/127 |
| `lesson_attempts.results` | JSON list `[{type,index,correct,solution}]` |

**Kết luận:** trên **dữ liệu thật** không thể fit/evaluate BKT có ý nghĩa. Nhiệm vụ phase là
**dựng hạ tầng đo đúng** + **công bố trung thực `INSUFFICIENT_DATA`** trên dữ liệu thật,
và kiểm chứng *tính đúng của thuật toán* trên dữ liệu **mô phỏng có nhãn rõ**.

> Con số ở bảng này là **snapshot**, không hard-code vào test/acceptance.

## 3. Goals / Non-goals / Anti-goals

**Goals**
- Hàm BKT thuần Python (4 tham số kinh điển `P(L0)`, `learn`, `guess`, `slip`), ổn định số học.
- Extractor **read-only** từ DB thật: chuỗi `(user, skill, timestamp, y)` với
  `y = score_correct/score_total` (mục tiêu **mềm** 0..1, khớp đại lượng mastery đang dùng).
- Harness eval: baseline rule-based (tái lập `compute_mastery` **as-of** từng mốc) vs BKT;
  split theo **user** và **time cutoff**; metric Brier (mục tiêu mềm) + AUC (mục tiêu nhị
  phân) + log loss + calibration/ECE + drift + fairness slice; trả `INSUFFICIENT_DATA`
  khi dưới ngưỡng tối thiểu thay vì in số vô nghĩa.
- Report JSON + tóm tắt console, offline, không network, không tốn phí.

**Non-goals**
- Không thay `SkillMastery.mastery_score`, không đổi `method` trả ra API.
- Không DKT/LSTM, không bandit (P5.2).
- Không migration, không bảng prediction, không worker shadow.
- Không hyperparameter search lớn; chỉ grid nhỏ cố định, deterministic, ghi lại.

**Anti-goals**
- In ra "BKT tốt hơn baseline" khi n < ngưỡng, khi split leakage, hoặc khi so lệch mục tiêu.
- Gọi BKT đã "deploy"/"tích hợp production".
- Dùng dữ liệu mô phỏng để tuyên bố chất lượng trên người học thật.
- Fit trên test, hoặc split ngẫu nhiên theo attempt (leakage cùng user).

## 4. Constraint từ repo (FACT, kiểm tra hôm nay)

- Alembic head trên branch P5.0 là `0015_p50_learner_profile` (thư mục `backend/alembic`);
  DB dev vẫn `0012` ⇒ extractor **phải chịu được schema cũ** (không có `skills`/
  `lesson_skills`/`skill_mastery`). Thiếu bảng skill ⇒ chỉ dựng chuỗi mức **lesson**,
  report ghi `skillGranularity=false`.
- `lesson_attempts` UNIQUE `(lesson_id,user_id,client_attempt_id)`, cột
  `score_correct, score_total, content_version, created_at, duration_ms, results`.
- `Lesson.content_version` là version hiện hành; P5.0 chỉ tính attempt **khớp version**
  (`learner_profile_service.py:248`) ⇒ eval phải áp **cùng filter**, nếu không so sánh
  vô hiệu do 90/127 attempt stale.
- **Không** `numpy`/`sklearn` trong `requirements.txt` ⇒ BKT/AUC viết **pure Python**.
- `inspect(engine)` **không chạy** trên `AsyncEngine`; phải
  `async with engine.connect() as c: await c.run_sync(lambda s: inspect(s).get_table_names())`.
- Eval script **không** được gọi `Base.metadata.create_all` (khác `rag_eval.py`) — nếu gọi thì
  bảng luôn tồn tại và DB thật không bao giờ được đọc. Đọc DB qua `DATABASE_URL` hiện có,
  **không tạo bảng**, không ghi.
- `.env` mặc định `DATABASE_URL` là SQLite file, **không** phải Postgres Docker ⇒ script
  bắt buộc nhận `--database-url` (hoặc env override) và in rõ nguồn DB đã đọc.
- Convention eval: `backend/evals/*.py` có `__main__` + `argparse`, report JSON vào
  `backend/evals/reports/` (gitignored), output tiếng Việt, `sys.stdout.reconfigure` Windows.
- Test dùng SQLite in-memory; hàm thuần không gọi DB.

## 5. Phương án đã cân nhắc

| Phương án | Đổi lấy | Kết luận |
|---|---|---|
| A. Chỉ dataset + báo cáo thiếu dữ liệu, không code BKT | Ít code nhất; nhưng không review được công thức | Loại |
| **B. BKT thuần Python + extractor read-only + eval harness (không runtime)** | Review được công thức, chạy trên DB thật, không rủi ro schema/UX; kết quả trung thực | **CHỌN** |
| C. Như B + migration `bkt_predictions` + worker shadow | Có dữ liệu hiệu chuẩn sau này; thêm schema khi chưa chứng minh giá trị | Loại ở phase này |

## 6. Thiết kế chi tiết

### 6.1 `backend/app/services/bkt.py` (thuần, không I/O, không DB)

```python
@dataclass(frozen=True)
class BktParams:
    p_init: float = 0.3
    p_learn: float = 0.2
    p_guess: float = 0.2
    p_slip: float = 0.1

def validate(params) -> None            # 0<p<1 strict; guess+slip < 1
def observe(prior: float, y: float, params) -> float
def apply_learning(posterior: float, params) -> float
def predict_correct(priors: list[float], params) -> list[float]
    # P(correct) = P(L)(1-slip) + (1-P(L))*guess  -> MỤC TIÊU dự đoán
def predict_sequence(observations: list[float], params) -> list[float]
    # predict_sequence[i] dùng observations[:i] (prior ban đầu p_init)
```

Quy ước rõ (giải quyết ambiguity):
- **Mục tiêu so sánh là `y = score_correct/score_total` ∈ [0,1]** cho cả hai mô hình
  (mục tiêu mềm). Brier = `(p - y)²`.
- `predict_correct` nhận **prior P(L)** và trả **xác suất đúng**, dùng `guess`/`slip`.
  `observe` nhận quan sát **mềm** `y`: `P(L|y) ∝ P(y|L)·P(L)` với
  `P(y|L)=1-slip` khi `y≥0.5`, `P(y|¬L)=guess`; để giữ tính liên tục của mục tiêu mềm,
  áp dụng Bayes mềm: `p_correct_given_mastery = (1-slip)*y + slip*(1-y)` và
  `p_correct_given_not = guess*y + (1-guess)*(1-y)`. Ghi rõ công thức trong docstring.
- AUC đo trên **nhãn nhị phân** `y >= threshold` (threshold mặc định 0.8 = policy P1.1),
  báo kèm threshold; AUC baseline hằng số = 0.5 theo định nghĩa (ghi rõ).
- `fit_sequence`: grid nhỏ cố định **dùng chung toàn bộ train set** (không per-sequence),
  chọn theo Brier train; deterministic, log lưới đã thử.

Ràng buộc: mọi output clamp `[eps, 1-eps]`; `predict_sequence[i]` không dùng tương lai;
tham số không hợp lệ ⇒ `ValueError`.

### 6.2 `backend/evals/mastery_dataset.py` (read-only)

- Kết nối `DATABASE_URL` (hoặc `--database-url`), **không** `create_all`, **không** commit.
- `await detect_capabilities(engine)` dùng `run_sync(inspect)` → có bảng skill hay không.
- `load_sequences(engine, granularity="lesson"|"skill"|"question")`:
  - **Mặc định `--granularity skill`** khi có bảng skill, fallback `lesson` (in cảnh báo).
  - Event = `(created_at, y=score_correct/score_total)` chỉ với attempt **khớp version**,
    `score_total > 0`; sort tăng dần theo `created_at`.
  - `skill`: JOIN `lesson_skills` + `skills`; một attempt thuộc **một** skill (P2.1: 1 skill/bài).
  - `question`: lấy từ `results` (`{index,correct}`, `correct` boolean) — chỉ dùng để đo
    độ dài chuỗi, **không** có skill gán ⇒ không đưa vào gate chính.
- Trả `DatasetReport`: `tableSource` (DSN đã che mật khẩu), `skillGranularity`, số user,
  phân bố độ dài chuỗi, số **chuỗi** (user,skill) có ≥ `min_sequence`, số event dùng được.
- Print cảnh báo nếu `DATABASE_URL` là SQLite file.

### 6.3 `backend/evals/bkt_eval.py`

CLI: `--dataset real|simulated`, `--database-url`, `--granularity skill|lesson`,
`--min-sequence 5`, `--min-sequences 30`, `--min-events 300`, `--seed`, `--json`, `--save`.

- **real**: nếu không đạt ngưỡng ⇒ in `INSUFFICIENT_DATA` + **đúng lý do** (ví dụ
  "0 chuỗi ≥5 event; cần 30"), exit 0, report `status="insufficient_data"`.
- **simulated**: sinh chuỗi từ tham số BKT đã biết, seed cố định, report
  `"dataSource": "simulated"`; dùng để chứng minh cập nhật đúng + split/metric hoạt động —
  **không** suy rộng.
- **Split:** `user` (mặc định; không user nào ở cả hai phía) và `time` (cutoff lấy từ
  phân vị thời gian). Report cả hai; gate dùng split `user`.
- **Baseline (as-of, không leakage):** tại mỗi event `t` của test, dự đoán
  `p_t = Σ w_i y_i / Σ w_i` trên **attempt prior cùng version** (cùng user+skill),
  `w_i = 0.5^((t-t_i)/30 ngày)`; thiếu prior ⇒ dùng prior mặc định = trung bình train
  (ghi rõ). **Không** gọi `compute_mastery(now=…)`.
- **BKT:** fit grid trên train (dùng chung), dự đoán test as-of.
- **Metric:** Brier (mục tiêu mềm), log loss clamp, AUC nhị phân (threshold 0.8),
  calibration 10 bins + ECE, **drift** (Brier theo nửa thời gian sớm/muộn của test),
  **fairness slice** (theo số event của user: ít/nhiều; chỉ báo, không tuyên bố công bằng
  tuyệt đối khi n nhỏ). Ghi kèm n/seed/tham số/lưới.
- Output tiếng Việt + `PHASE GATE` theo ngưỡng §6.4.

### 6.4 Ngưỡng go/no-go (PROPOSAL, cần hiệu chỉnh khi có dữ liệu)

Gate dùng **chuỗi** (user, skill), không phải user:

| Tiêu chí | Ngưỡng đề xuất |
|---|---|
| Số **chuỗi** (user,skill) có ≥ 5 event, thuộc split train **và** test | ≥ 30 (mỗi phía ≥ 10) |
| Tổng event dùng được (khớp version) | ≥ 300 |
| BKT Brier < baseline Brier | chênh ≥ 2% tương đối |
| ECE | ≤ 0.10 |
| AUC (nhị phân @0.8) | ≥ 0.60 |
| Drift: Brier nửa sau − nửa đầu | ≤ 0.05 |
| Leakage | 0 user/skill sequence ở cả train và test |

Bất kỳ tiêu chí fail ⇒ `gate="NOT_MET"`, **không** đề xuất deploy. Với snapshot hiện tại
(`0` chuỗi ≥5), dự kiến kết quả là `INSUFFICIENT_DATA`, không phải `NOT_MET`.

### 6.5 File chạm

| File | Loại |
|---|---|
| `backend/app/services/bkt.py` | mới (thuần) |
| `backend/evals/mastery_dataset.py` | mới (read-only) |
| `backend/evals/bkt_eval.py` | mới (`__main__`) |
| `backend/tests/test_p51_bkt.py` | mới |
| `backend/tests/test_p51_dataset.py` | mới (SQLite in-memory) |
| `docs/specs/12-ADAPTIVE-LEARNING.md` | cập nhật mục BKT |
| `docs/specs/23-P51-BKT.md` | mới (spec/limit) |
| `docs/development-progress.md` | report phase |
| `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` | đánh dấu P5.1 research-only |

**Không chạm:** `models.py`, `alembic/`, `api/`, `frontend/`, `core/config.py`,
`learner_profile_service.py`, `learning_path_service.py`.

### 6.6 Rollback

Không migration, không runtime ⇒ rollback = revert commit. Không ảnh hưởng dữ liệu.

## 7. Acceptance / Gate

1. Test hàm thuần: clamp 0/1; chuỗi toàn đúng ⇒ tăng đơn điệu; toàn sai ⇒ giảm;
   `predict_sequence` không dùng tương lai; `guess+slip≥1` ⇒ `ValueError`; `observe` với
   `y∈{0,0.5,1}` đúng công thức; soft-y hội tụ về hard-y khi `y→0/1`.
2. Extractor chạy read-only trên **DB thật**: in DSN đã che, số liệu khớp
   `psql` (không hard-code), **không** tạo/ghi bảng; chạy được trên schema `0012`
   (không có bảng skill) và trên schema `0015` (có) — test SQLite in-memory dựng 2 schema.
3. `python -m evals.bkt_eval --dataset real --database-url …` ⇒ `INSUFFICIENT_DATA` kèm
   lý do định lượng; exit 0; **không** in `PASS`.
4. `--dataset simulated --save` ⇒ report có `dataSource=simulated`, seed, split 0-leakage,
   metric + ECE + drift + slice; chứng minh BKT > baseline trên dữ liệu mô phỏng khớp mô hình.
5. `pytest -q` vẫn xanh; số test mới được đếm lại thực tế tại thời điểm chạy (không chép
   con số cũ).
6. `git diff --stat` chứng minh không file models/alembic/api/config runtime bị sửa.

## 8. Việc để builder quyết

- `min-sequence=5`, `min-sequences=30`, `min-events=300` (đề xuất; ghi vào `--help`).
- ECE: 10 bins đều theo xác suất, bin rỗng bị loại khỏi ECE (ghi rõ).
- AUC rank-based (~30 dòng) và slice fairness mức "báo cáo, không kết luận".
- Có lưu report simulated vào `backend/evals/reports/` (đã gitignored).
