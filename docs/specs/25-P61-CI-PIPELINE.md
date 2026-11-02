# 25 — P6.1 CI Pipeline & Automated Gates

**Trạng thái:** IMPLEMENTED + TESTED (local simulation). **GitHub Actions run thật chưa
được quan sát** — không có push/PR nào trong phiên này, nên xem là NOT TESTED trên runner.

## 1. Mục tiêu

Mỗi thay đổi vào `main` phải trả lời được *bằng máy*: test backend còn pass, migration
chạy được trên PostgreSQL rỗng và lùi được một bước, race test thật trên PostgreSQL vẫn
đúng, frontend lint/typecheck/build không lỗi, và không có advisory bảo mật mức cao trong
dependency runtime.

Không có bước nào gọi provider LLM thật, deploy, hay chạm dữ liệu ngoài runner.

## 2. Các job

| Job | Nội dung | Gate |
|---|---|---|
| `backend-tests` | `python -m pytest -q` (SQLite in-memory, mock provider) | 0 fail, 0 error |
| `postgres-migrations` | `alembic upgrade head` trên DB rỗng → `downgrade -1` → `upgrade head` | cả 3 lệnh exit 0 |
| `postgres-race` | `pytest -k postgres_concurrency` với `POSTGRES_TEST_URL` | 0 fail (không skip) |
| `frontend` | `npm ci` → `lint` → `typecheck` → `build` | exit 0, lint `--max-warnings=0` |
| `security` | `bandit -r app`, `pip-audit -r requirements.txt`, `npm audit --omit=dev --audit-level=high` | không issue mức Medium/High; không advisory high ở dep runtime |

Trigger: push lên `main`/`feat/**`, PR vào `main`, `workflow_dispatch`.
`permissions: contents: read`, `concurrency` cancel-in-progress. CI **không đọc
`secrets.*`** để PR từ fork vẫn chạy được (có test chặn).

## 3. Thay đổi về gate frontend (lý do)

1. **`next lint` bị loại khỏi script `lint`.** Khi chưa có cấu hình ESLint, `next lint`
   mở **wizard tương tác** và treo CI. Nay dùng ESLint flat config trực tiếp:
   `eslint . --max-warnings=0`.
2. **Warning chặn merge**, không chỉ error — nếu không, cảnh báo `no-unused-vars` sẽ
   tích tụ thành nhiễu không ai đọc. Bốn warning có sẵn đã được dọn (import/biến không dùng).
3. **`eslint-config-next` pin cùng version với `next`** để hai bên không lệch rule.
4. **`typecheck` tách riêng** khỏi `build` để log lỗi TS rõ ràng, không bị lẫn với output
   bundler.

## 4. Nâng `next` 15.1.6 → 15.5.28 (bắt buộc)

`npm audit` trên baseline báo advisory **critical/high** cho `next@15.1.6`: RCE trên
Image Optimization (AVIF/SVG), RCE trên Windows-hosted server, DoS qua Server Actions,
cache poisoning, SSRF qua rewrites. Đã pin **`next@15.5.28`** (bản backport mới nhất của
major 15) và `eslint-config-next@15.5.28`.

`postcss` (transitive, `<=8.5.22`) vẫn dính path traversal/source-map read khi Next ghim
`8.4.31`. Thêm `overrides: {"postcss": "^8.5.32"}` ⇒ `npm audit --omit=dev` = **0
vulnerabilities**.

**Không** nâng lên Next 16: đó là breaking change ngoài phạm vi P6.1 (không được trộn
nâng major framework với việc dựng CI).

### Baseline còn lại (đã ghi nhận, không tự sửa)

| Advisory | Mức | Phạm vi | Quyết định |
|---|---|---|---|
| `minimatch < 11.0.1` (DoS qua globparts) | moderate | **dev-only** qua `@typescript-eslint` | Gate ở `--omit=dev --audit-level=high` nên không chặn; `npm audit fix --force` sẽ hạ cấp/đổi major toolchain — không tự làm. Theo dõi khi `eslint-config-next` nâng. |

## 5. Fix pass sau review (Critical/Important)

Fresh review của branch tìm ra một lỗ hổng thật và bốn chỗ gate có thể "xanh giả".
Đã sửa trong **một** pass, mỗi fix có test đỏ→xanh.

### C1 — Hoán vị `order`/`match` suy ra được từ dữ liệu công khai (Critical)

`_seed` cũ là `sha256("<lessonId>:<version>:<blockIndex>")`. Cả ba thành phần đều
công khai: `lessonId` nằm trong URL (`lsn_<uuid>`), `contentVersion`/`blockIndex`
nằm trong payload. Tôi đã dựng lại **đúng** hoán vị bằng script chỉ dùng dữ liệu
public và khôi phục đáp án `order`; với `match`, `lefts` phát ra theo thứ tự cặp
private nên đảo hoán vị `rights` là ra toàn bộ mapping. Nghĩa là học viên (hoặc
script) giải hết quiz mà không cần biết nội dung — trái với docstring và
`AGENTS.md`.

Đây là lỗi có **trước** P6.1, nhưng bản trước của nhánh này còn thêm comment khẳng
định "không suy ra được từ thứ tự" và `# nosec` che nó ⇒ phải sửa cùng lúc.

Cách sửa: seed = `HMAC-SHA256(khoá server, "<lessonId>:<version>:<blockIndex>")`,
khoá lấy từ `LESSON_SHUFFLE_SECRET` (fallback `JWT_SECRET`). Khoá không rời
server ⇒ không tái lập được hoán vị.

| Trạng thái | Hành vi |
|---|---|
| `LESSON_SHUFFLE_SECRET` đặt | Khoá riêng cho shuffle |
| Rỗng, có `JWT_SECRET` | Dùng `JWT_SECRET` — **mặc định an toàn**, không cần cấu hình thêm |
| Rỗng cả hai, `ENV != production` | Khoá dev cố định + `logger.warning` |
| Rỗng cả hai, `ENV == production` | **`RuntimeError`** — không âm thầm dùng khoá công khai |

Hệ quả vận hành phải biết:

- **Xoay khoá làm sai quiz đang làm dở.** Học viên đã nhận thứ tự theo khoá cũ;
  POST submit được chấm theo khoá mới ⇒ đáp án đúng bị tính sai. Xoay khoá nên
  làm cùng lúc với việc publish `contentVersion` mới, hoặc chấp nhận mất attempt
  đang mở.
- **Mọi replica phải dùng cùng khoá.** Fallback `JWT_SECRET` đã là biến chung sẵn;
  nếu đặt `LESSON_SHUFFLE_SECRET` riêng thì phải set giống nhau ở `backend`,
  `worker`, `beat` — đã thêm vào `docker-compose.yml` cho cả `backend` và `worker`.
- Không có migration: projection tính lại mỗi request, không lưu hoán vị vào DB.

Test: `test_shuffle_seed_is_keyed_and_not_reproducible_from_public_data`,
`test_shuffle_seed_changes_when_server_secret_changes`,
`test_production_without_any_secret_refuses_to_shuffle` (đều RED trước fix).

### I1 — Race test chỉ pass nhờ thứ tự module (Important)

`test_p50_postgres_concurrency.py` và `test_p52_postgres_concurrency.py` chỉ
`create_async_engine` rồi seed ngay. Chạy **một mình** trên DB rỗng ⇒
`UndefinedTableError: relation "users" does not exist`; chúng chỉ xanh vì một
module race khác (xếp trước theo alphabet, có `create_all`) đã tạo schema. Fixture
nay tự `create_all`. Đã kiểm chứng: chạy riêng từng file trên DB rỗng mới ⇒ pass,
và **stash fix ⇒ đỏ** đúng như mô tả.

### I2 — Job race không trỏ `DATABASE_URL` sang PostgreSQL (Important)

Chỉ `POSTGRES_TEST_URL` được set, nên code resolve settings (`SessionLocal`,
`llm_usage_service.record_standalone`) vẫn chạy SQLite trong một job tên là
"PostgreSQL concurrency tests". Nay cả hai biến set ở **job level**.

### I3 — Gate có thể pass giả khi mọi test bị skip (Important)

`pytest` thoát **0** khi tất cả test bị skip. Một lỗi chính tả trong tên biến môi
trường ⇒ job xanh mà chạy 0 test DB. Thêm bước guard kiểm tra
`POSTGRES_TEST_URL` bắt đầu bằng `postgresql+asyncpg://`, và test contract chặn
`|| true` / `continue-on-error: true` trong mọi step.

### I4 — Bước "verify revisions" chỉ in history (Important)

`alembic history --verbose` không chứng minh `downgrade()` chạy được. Nay:
`downgrade base → upgrade head → current`, cộng kiểm tra graph chỉ có **một** head.

### I5 — `@eslint/eslintrc` không được khai báo (Important)

`eslint.config.mjs` import trực tiếp nhưng package không nằm trong
`devDependencies` — chỉ resolve được nhờ npm hoist. Đã thêm `@eslint/eslintrc@3.3.7`.

### Minor trong pass này

- `postgres-race` cài `requirements-dev.txt` (test contract cần PyYAML).
- `pip-audit` đặt `PYTHONUTF8=1` và quét **cả** `requirements-dev.txt`.
- Commit `next-env.d.ts` theo dạng Next 15.5 sinh ra, để `npm run build` không
  làm bẩn working tree.

## 6. Static analysis backend — sửa thật, không `# nosec` mù

Bandit ban đầu báo 8 issue. Cách xử lý:

| Test | Vị trí | Xử lý |
|---|---|---|
| B101 `assert` | `api/v1/tutor.py`, `providers/openai_compatible_provider.py` ×2 | **Sửa code**: thay bằng kiểm tra tường minh + raise (`RuntimeError`, `SchemaInvalidError`, `ProviderTransientError`). `assert` bị bỏ khi chạy `python -O` ⇒ đây là lỗi thật, không phải false positive. |
| B311 `random` | `lesson_content._shuffled`, `_backoff` jitter | Giữ + `# nosec B311` **có lý do**: PRNG tất định theo seed cho shuffle/backoff, không dùng làm giá trị bảo mật; đáp án đúng nằm server-side. |
| B110 `try/except/pass` | `services/storage.py`, `services/url_fetcher.py` | Giữ + `# nosec B110` **có lý do**: đóng connection/transport best-effort trong `finally`, không được che lỗi đã raise trước đó. |
| B105 "password" | `TUTOR_TOKEN_LIMIT_REACHED` | False positive: mã lỗi hằng chuỗi, không phải secret. `# nosec B105`. |

Kết quả: **0 Low / 0 Medium / 0 High**, 5 chỗ `# nosec` đều có comment giải thích.

`pip-audit -r requirements.txt` → **No known vulnerabilities found**.

## 7. Test bảo vệ chính CI

`backend/tests/test_p61_ci_contract.py` (**15 test**) đọc `ci.yml` + `package.json` và
khẳng định: job bắt buộc tồn tại, trigger PR vào `main`, `permissions.contents == read`,
không dùng `secrets.*`, migration job có `downgrade -1` **và** `downgrade base` cộng
kiểm tra graph một head, race job trỏ **cả** `POSTGRES_TEST_URL` lẫn `DATABASE_URL` sang
PostgreSQL và có bước guard chống skip-im-lặng, mọi step cấm `|| true`/
`continue-on-error: true`, frontend chạy đủ 4 lệnh, security job phủ cả Python lẫn Node
và quét cả `requirements-dev.txt`, script lint không quay lại `next lint` và có
`--max-warnings=0`, `next` pin khớp `eslint-config-next` và `>=15.5.28`,
`@eslint/eslintrc` được khai báo tường minh.

Đã kiểm chứng test này **thật sự bắt lỗi** (không tautological):

| Kịch bản tiêm | Kết quả |
|---|---|
| Đổi `lint` về `next lint` | 1 failed → khôi phục: 15 passed |
| Bỏ khai báo `@eslint/eslintrc` | 1 failed → thêm lại: 15 passed |
| Bỏ job / `|| true` / đổi race env | có assert riêng cho từng cái |

## 8. Bằng chứng đã chạy (local, Windows)

```bash
cd backend && python -m pytest -q
# 698 passed, 29 skipped, 17 warnings in 70.50s

cd backend && python -m bandit -r app
# Total issues: Low 0 / Medium 0 / High 0

cd backend && PYTHONUTF8=1 python -m pip_audit -r requirements.txt --progress-spinner off
# No known vulnerabilities found

cd frontend && npm ci && npm run lint && npm run typecheck && npm run build
# npm_ci_exit=0 lint_exit=0 tsc_exit=0 build_exit=0

cd frontend && npm audit --omit=dev --audit-level=high
# found 0 vulnerabilities

# PostgreSQL throwaway (database tạo rồi drop trong phiên):
DATABASE_URL=postgresql+asyncpg://ailp:***@127.0.0.1:5433/p60_migration_check\
  alembic upgrade head            # -> 0016_p52_exposure (head)
DATABASE_URL=... alembic downgrade -1      # -> 0015_p50_learner_profile
DATABASE_URL=... alembic upgrade head      # -> 0016_p52_exposure (head)
DATABASE_URL=... alembic downgrade base    # -> schema rỗng
DATABASE_URL=... alembic upgrade head      # -> 0016_p52_exposure (head)

# Race test đúng như CI job race (CẢ HAI biến trỏ PostgreSQL):
POSTGRES_TEST_URL=postgresql+asyncpg://ailp:***@127.0.0.1:5433/p60_full\
DATABASE_URL=postgresql+asyncpg://ailp:***@127.0.0.1:5433/p60_full\
  python -m pytest tests -q -k postgres_concurrency --no-header -rs
# 29 passed, 698 deselected

# Race module phải chạy được MỘT MÌNH trên DB rỗng (I1):
POSTGRES_TEST_URL=.../p60_race_alone python -m pytest\
  tests/test_p50_postgres_concurrency.py tests/test_p52_postgres_concurrency.py -q
# 4 passed
```

## 9. NOT TESTED / giới hạn

- **GitHub Actions runner chưa chạy** (chưa push). Không được báo "CI green" khi chưa có
  run URL/log. Đây là việc của người có quyền push.
- **Docker build** backend/frontend với version mới: NOT TESTED (image build nặng, không
  cần cho gate P6.1; `npm run build` đã chạy).
- **Xoay khoá shuffle khi đang có attempt mở**: hệ quả đã biết (attempt đang mở bị chấm
  sai) nhưng chưa diễn tập trên dữ liệu thật — chưa có quy trình rotate được duyệt.
- **Nhiều replica đọc cùng khoá shuffle**: chưa chạy nhiều container để xác nhận.
- **Coverage threshold, SAST nâng cao (CodeQL/Semgrep), SBOM/license scan, OpenAPI diff
  check**: chưa làm — ngoài phạm vi tối thiểu, đề xuất cho P6.2/P6.9.
- **`pyright`/`mypy`** chưa bật cho backend: repo chưa có type-check baseline; bật ngay sẽ
  đỏ hàng loạt vì code cũ không annotate đầy đủ.

## 10. Lệnh vận hành local (Windows, không Docker)

```powershell
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
python -m bandit -r app -q
$env:PYTHONUTF8=1; python -m pip_audit -r requirements.txt --progress-spinner off
$env:PYTHONUTF8=1; python -m pip_audit -r requirements-dev.txt --progress-spinner off

# Race test thật (DB throwaway, không dùng DB ailp chính):
docker compose exec db psql -U ailp -d postgres -c "CREATE DATABASE p60_race;"
$env:POSTGRES_TEST_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p60_race"
$env:DATABASE_URL=$env:POSTGRES_TEST_URL
python -m pytest tests -q -k postgres_concurrency --no-header -rs

cd ..rontend
npm ci
npm run lint; npm run typecheck; npm run build
npm audit --omit=dev --audit-level=high
```

Kiểm chứng migration trên DB throwaway (an toàn, không chạm DB chính):

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p60_migration"
alembic upgrade head && alembic downgrade base && alembic upgrade head
alembic heads | wc -l   # phải = 1
```
