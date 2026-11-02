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

## 5. Static analysis backend — sửa thật, không `# nosec` mù

Bandit ban đầu báo 8 issue. Cách xử lý:

| Test | Vị trí | Xử lý |
|---|---|---|
| B101 `assert` | `api/v1/tutor.py`, `providers/openai_compatible_provider.py` ×2 | **Sửa code**: thay bằng kiểm tra tường minh + raise (`RuntimeError`, `SchemaInvalidError`, `ProviderTransientError`). `assert` bị bỏ khi chạy `python -O` ⇒ đây là lỗi thật, không phải false positive. |
| B311 `random` | `lesson_content._shuffled`, `_backoff` jitter | Giữ + `# nosec B311` **có lý do**: PRNG tất định theo seed cho shuffle/backoff, không dùng làm giá trị bảo mật; đáp án đúng nằm server-side. |
| B110 `try/except/pass` | `services/storage.py`, `services/url_fetcher.py` | Giữ + `# nosec B110` **có lý do**: đóng connection/transport best-effort trong `finally`, không được che lỗi đã raise trước đó. |
| B105 "password" | `TUTOR_TOKEN_LIMIT_REACHED` | False positive: mã lỗi hằng chuỗi, không phải secret. `# nosec B105`. |

Kết quả: **0 Low / 0 Medium / 0 High**, 5 chỗ `# nosec` đều có comment giải thích.

`pip-audit -r requirements.txt` → **No known vulnerabilities found**.

## 6. Test bảo vệ chính CI

`backend/tests/test_p61_ci_contract.py` (11 test) đọc `ci.yml` + `package.json` và khẳng
định: job bắt buộc tồn tại, trigger PR vào `main`, `permissions.contents == read`, không
dùng `secrets.*`, migration job có `downgrade -1` trên service PostgreSQL, race job đặt
`POSTGRES_TEST_URL`, frontend chạy đủ 4 lệnh, security job phủ cả Python và Node, script
lint không quay lại `next lint` và có `--max-warnings=0`, `next` pin khớp
`eslint-config-next` và `>=15.5.28`.

Đã kiểm chứng test này **thật sự bắt lỗi**: tạm đổi `lint` về `next lint` ⇒ 1 failed;
khôi phục ⇒ 11 passed.

## 7. Bằng chứng đã chạy (local, Windows)

```bash
cd backend && python -m pytest -q
# 691 passed, 29 skipped, 17 warnings in 108.45s

cd backend && python -m bandit -r app
# Total issues: Low 0 / Medium 0 / High 0

cd backend && PYTHONUTF8=1 python -m pip_audit -r requirements.txt --progress-spinner off
# No known vulnerabilities found

cd frontend && npm ci && npm run lint && npm run typecheck && npm run build
# npm_ci_exit=0 lint_exit=0 tsc_exit=0 build_exit=0

cd frontend && npm audit --omit=dev --audit-level=high
# found 0 vulnerabilities

# PostgreSQL throwaway (database tạo rồi drop trong phiên):
DATABASE_URL=postgresql+asyncpg://ailp:***@127.0.0.1:5433/p60_migration_check \
  python -m alembic upgrade head       # -> 0016_p52_exposure (head)
DATABASE_URL=... python -m alembic downgrade -1   # -> 0015_p50_learner_profile
DATABASE_URL=... python -m alembic upgrade head   # -> 0016_p52_exposure (head)

POSTGRES_TEST_URL=postgresql+asyncpg://ailp:***@127.0.0.1:5433/p60_race_check \
  python -m pytest tests -q -k postgres_concurrency
# 29 passed, 680 deselected
```

## 8. NOT TESTED / giới hạn

- **GitHub Actions runner chưa chạy** (chưa push). Không được báo "CI green" khi chưa có
  run URL/log. Đây là việc của người có quyền push.
- **Docker build** backend/frontend với version mới: NOT TESTED (image build nặng, không
  cần cho gate P6.1; `npm run build` đã chạy).
- **Coverage threshold, SAST nâng cao (CodeQL/Semgrep), SBOM/license scan, OpenAPI diff
  check**: chưa làm — ngoài phạm vi tối thiểu, đề xuất cho P6.2/P6.9.
- **`pyright`/`mypy`** chưa bật cho backend: repo chưa có type-check baseline; bật ngay sẽ
  đỏ hàng loạt vì code cũ không annotate đầy đủ.

## 9. Lệnh vận hành local (Windows, không Docker)

```powershell
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
python -m bandit -r app -q
$env:PYTHONUTF8=1; python -m pip_audit -r requirements.txt --progress-spinner off
cd ..\frontend
npm ci
npm run lint; npm run typecheck; npm run build
npm audit --omit=dev --audit-level=high
```
