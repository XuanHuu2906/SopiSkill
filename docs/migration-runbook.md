# Runbook — Chuyển database hiện có sang Alembic (không mất dữ liệu)

> Áp dụng cho database đã được tạo bằng `Base.metadata.create_all()` trước khi có Alembic.

## Bối cảnh

Database cũ (PostgreSQL trong Docker volume `pgdata`) có schema sinh bởi `create_all()`
tại thời điểm slice 1 — **không có bảng `alembic_version`**. Migration `0001_initial`
được viết khớp chính xác schema đó (đã xác minh bằng `information_schema` trước khi
stamp — xem `docs/development-progress.md` mục 2026-10-30 P0.5).

## Nguyên tắc an toàn

1. **Backup trước — mọi thao tác sau.**
2. **Không tự động stamp** — chỉ stamp sau khi đã so khớp schema cũ với migration.
3. Không `drop_all()`, không xóa volume.
4. Chạy migration khi backend + worker đã **stop** (tránh ghi dữ liệu giữa chừng).

## Các bước (đã thực hiện 2026-10-30, chứng minh bên dưới)

### 1. Backup

```bash
docker compose exec db pg_dump -U ailp ailp > backup_pre_migration_$(date +%Y%m%d_%H%M%S).sql
# Kiểm tra backup có dữ liệu:
grep -c "^COPY" backup_pre_migration_*.sql   # phải > 0
```

### 2. So khớp schema cũ với migration 0001

```bash
docker compose exec db psql -U ailp -d ailp -c "
  SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
docker compose exec db psql -U ailp -d ailp -c "
  SELECT column_name, data_type FROM information_schema.columns
  WHERE table_name='users' ORDER BY ordinal_position;"
docker compose exec db psql -U ailp -d ailp -c "
  SELECT typname FROM pg_type WHERE typtype='e'
    AND typname IN ('course_status','job_status','lesson_status');"
```

So sánh kết quả với nội dung `backend/alembic/versions/0001_initial.py`.
Phải khớp: 9 bảng, kiểu cột (uuid, text, jsonb, enum...), index, unique constraints.

### 3. Stop app, stamp migration tương ứng, rồi upgrade

```bash
docker compose stop backend worker
docker compose run --rm backend alembic stamp 0001_initial   # khai báo "schema đã tồn tại = 0001"
docker compose run --rm backend alembic current              # xác nhận: 0001_initial (head)
docker compose run --rm backend alembic upgrade head         # chạy các migration MỚI hơn (vd 0002)
docker compose up -d
```

### 4. Xác minh sau migration

```bash
docker compose exec db psql -U ailp -d ailp -c "
  SELECT column_name, is_nullable FROM information_schema.columns
  WHERE table_name='users' AND column_name IN ('email','password_hash');"
docker compose exec db psql -U ailp -d ailp -c "SELECT count(*) FROM users;"   # giữ nguyên số liệu cũ
curl http://127.0.0.1:8001/health
python backend/e2e_acceptance.py
```

### Rollback (nếu cần)

```bash
docker compose stop backend worker
docker compose run --rm backend alembic downgrade -1     # hoặc downgrade base
docker compose exec -T db psql -U ailp -d ailp < backup_pre_migration_*.sql  # khôi phục khi cần
```

> Lưu ý: `downgrade` của 0002 xóa 2 cột auth; khôi phục từ backup chỉ dùng khi
> schema rollback gây lỗi và đã được phê duyệt.

## Kết quả đã xác minh (2026-10-30)

- Backup: `backup_pre_migration_20261030_221411.sql` (9 COPY statements — có dữ liệu).
- Stamp `0001_initial` + `upgrade head` → `0002_auth_columns` thành công.
- 16 users + 16 courses cũ **giữ nguyên**; 2 cột `email`, `password_hash` được thêm (nullable).
- Backend up, E2E acceptance 21/21 PASS sau migration.

## P3.0 — revision `0005_p30_source_registry` (expand-only)

Thay đổi: bảng `sources`, `course_sources`, `lesson_citations` + cột `lessons.grounding`
(server_default `'general_ai_knowledge'`). Không drop/sửa cột cũ; không backfill dữ liệu giả.

### Kiểm chứng đã chạy (2026-10-31, DB throwaway `p30_migration_check`)

```bash
docker compose exec -T db psql -U ailp -d postgres -c "DROP DATABASE IF EXISTS p30_migration_check;" -c "CREATE DATABASE p30_migration_check;"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p30_migration_check" alembic upgrade head   # exit 0
DATABASE_URL=… alembic current          # 0005_p30_source_registry (head)
```

Kết quả: 13 bảng (9 cũ + 4 mới), enum `lesson_grounding` tồn tại, `lessons.grounding`
NOT NULL default `'general_ai_knowledge'`.

### Rollback đã kiểm chứng

```bash
DATABASE_URL=… alembic downgrade 0004_p12_job_reliability   # exit 0
# → còn 10 bảng (sources/course_sources/lesson_citations bị drop), cột grounding bị drop,
#   các enum P3.0 bị drop; enum course/job/lesson giữ nguyên.
DATABASE_URL=… alembic upgrade 0004_p12_job_reliability     # forward recovery OK
```

### Bài học cũ vẫn đọc được (đã kiểm chứng)

Seed 1 user/course/unit/lesson "legacy" ở revision 0004 → `upgrade head` → truy vấn ORM:

```
legacy lesson: Legacy lesson | grounding = general_ai_knowledge | version = 1
sources table readable, count = 0
```

### Giới hạn rollback (ghi rõ)

- `downgrade` **mất** toàn bộ metadata nguồn, liên kết course–source và citation tạo sau P3.0.
  Không thể khôi phục từ schema; cần restore backup nếu muốn quay lui có dữ liệu.
- Trên DB thật: backup trước (`pg_dump`), dừng backend/worker, rồi mới downgrade.
- `lessons.content`/attempt/progress **không** bị đụng khi rollback.

## P2.SR — revision `0006_p2sr_source_research`

```bash
# throwaway check (đã chạy 2026-10-31)
docker exec <db> psql -U ailp -d postgres -c "CREATE DATABASE p2sr_migration_check;"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p2sr_migration_check" \
  python -m alembic upgrade head          # → 0006_p2sr_source_research (head), 14 bảng
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p2sr_migration_check" \
  python -m alembic downgrade 0005_p30_source_registry
                                          # → drop source_research_runs + enum, còn 13 bảng
```

Đã kiểm chứng thêm: seed user/course/unit/lesson ở revision 0005 (`content_version=3`) → upgrade
head → ORM đọc `grounding=general_ai_knowledge`, `content_version=3`, course `ready` ⇒ không mất
dữ liệu. DB dev `ailp` đã upgrade lên 0006 sau backup `backup_pre_p2sr_*.sql`.

Rollback mất **lịch sử research run** (không ảnh hưởng course/lesson/attempt/citation).

## P2.2 — revision `0007_p22_eval_cost`

```bash
# throwaway check (đã chạy 2026-10-31)
docker exec <db> psql -U ailp -d postgres -c "CREATE DATABASE p22_migration_check;"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p22_migration_check"   python -m alembic upgrade head             # → 0007_p22_eval_cost (head)
# introspection: bảng llm_usage_events + 4 cột trên generation_jobs (llm_calls NOT NULL default 0)
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p22_migration_check"   python -m alembic downgrade 0006_p2sr_source_research   # drop bảng + 4 cột (đã kiểm chứng)
```

Seed legacy ở revision 0006 (user/course/generation_job `ready`) → upgrade head →
`llm_calls=0`, `prompt_tokens/completion_tokens/cost_estimate_usd = NULL` ⇒ **không mất dữ liệu**,
và `cost_estimate_usd = NULL` được đọc đúng nghĩa "chưa biết giá" (không phải 0).

DB dev `ailp` đã backup (`backup_pre_p22_*.sql`, 14 COPY) và upgrade lên 0007.

Rollback mất **lịch sử usage/chi phí** (không ảnh hưởng course/lesson/attempt/job/citation).

## P3.0 Tutor — revision `0008_p30_tutor_core`

Thay đổi (expand-only): 2 bảng mới + 2 enum + 4 index; **không** sửa cột/bảng cũ.

```bash
# throwaway check (đã chạy 2026-10-31)
docker exec reverseengineer-db-1 psql -U ailp -d postgres   -c "DROP DATABASE IF EXISTS p30_tutor_migration_check"   -c "CREATE DATABASE p30_tutor_migration_check"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p30_tutor_migration_check"   python -m alembic upgrade head        # → 0008_p30_tutor_core (head), 17 bảng
DATABASE_URL=… python -m alembic current
```

Kết quả introspection `tutor_messages`: `position` NOT NULL default 0, `course_id` NOT NULL
(cột denormalized để UNIQUE hoạt động), `context_ref jsonb`, `UNIQUE(course_id,
client_message_id, role)` tên `uq_tutor_message_client_id`, index
`(thread_id, position)`; FK tới `courses`, `tutor_threads`, `users`, `lessons`.

### Rollback đã kiểm chứng

```bash
DATABASE_URL=… python -m alembic downgrade 0007_p22_eval_cost   # exit 0
# → còn 15 bảng, 2 bảng tutor + 2 enum biến mất
DATABASE_URL=… python -m alembic upgrade head                   # forward recovery OK
```

### Bài học/khóa học cũ vẫn đọc được (đã kiểm chứng)

Seed user/course/unit/lesson ở revision 0007 (`content_version=3`) → `upgrade head` →
`title='L'`, `content_version=3`, `status='ready'`, `grounding='general_ai_knowledge'`,
`tutor_threads` count = 0 ⇒ **không mất dữ liệu**, không backfill giả.

### Giới hạn rollback

- `downgrade` **mất** toàn bộ thread/message tutor. Không khôi phục được từ schema; cần restore
  backup (`backup_pre_p30_tutor_*.sql`) nếu muốn quay lui có dữ liệu hội thoại.
- `lessons.content`, attempt, progress, source, citation **không** bị đụng.
- DB dev `ailp` đã backup trước khi upgrade (xem `docs/development-progress.md`).

### Race test (PostgreSQL throwaway `p30_tutor_race_check`)

```bash
POSTGRES_TEST_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p30_tutor_race_check"   python -m pytest tests/test_p30_tutor_postgres_concurrency.py -q    # 2 passed
```

## P3.1 Tutor controls — revision `0009_p31_tutor_controls`

Thay đổi (expand-only): thêm cột nullable `tutor_messages.cancel_requested_at`, index
`ix_tutor_messages_status`, bảng `tutor_usage_events` (+2 index). Không đổi kiểu cột cũ,
không thêm cột NOT NULL ⇒ không cần backfill.

```bash
# throwaway check (đã chạy 2026-10-31)
docker exec reverseengineer-db-1 psql -U ailp -d postgres   -c "DROP DATABASE IF EXISTS p31_tutor_migration_check"   -c "CREATE DATABASE p31_tutor_migration_check"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p31_tutor_migration_check"   python -m alembic upgrade head                       # → 0009_p31_tutor_controls (head), 18 bảng
DATABASE_URL=… python -m alembic downgrade 0008_p30_tutor_core   # → 17 bảng, bảng usage + cột + index biến mất
DATABASE_URL=… python -m alembic upgrade head                    # forward recovery OK
```

Introspection đã kiểm: `tutor_usage_events` có 11 cột (không có cột nội dung/prompt), FK tới
`users`/`courses`/`tutor_messages`, index `(user_id, created_at)`; `cancel_requested_at` nullable.

### Dữ liệu cũ vẫn đọc được (đã kiểm chứng)

Seed user/course/unit/lesson (`content_version=3`) + thread + assistant message `completed` ở
revision 0008 → `upgrade head` → lesson giữ `content_version=3`/`status=ready`/grounding cũ,
message giữ `status=completed`, `content='cũ'`, `cancel_requested_at IS NULL`,
`tutor_usage_events` = 0 row ⇒ **không mất dữ liệu**, không backfill giả.

### Race test (PostgreSQL throwaway `p31_tutor_race_check`)

```bash
POSTGRES_TEST_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p31_tutor_race_check"   python -m pytest tests/test_p31_tutor_postgres_concurrency.py -q     # 4 passed
```

### Giới hạn rollback

- `downgrade` mất **usage event** của tutor và cờ stop đang chờ (không khôi phục từ schema).
- Thread/message/course/lesson/source/citation **không** bị đụng.
- DB dev `ailp` đã backup (`backup_pre_p31_20261031_140156.sql`, trong container db) trước upgrade.

## P3.1 lát B Tutor tool audit — revision `0010_p31_tutor_tools`

Thay đổi (expand-only): thêm bảng `tutor_tool_calls` + 4 index; **không** sửa cột/bảng cũ.

```bash
# throwaway check (đã chạy 2026-10-31)
docker exec reverseengineer-db-1 psql -U ailp -d postgres   -c "DROP DATABASE IF EXISTS p31b_migration_check"   -c "CREATE DATABASE p31b_migration_check"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p31b_migration_check"   python -m alembic upgrade head                          # → 0010_p31_tutor_tools (head), 19 bảng
DATABASE_URL=… python -m alembic downgrade 0009_p31_tutor_controls   # → 18 bảng, tutor_tool_calls biến mất
DATABASE_URL=… python -m alembic upgrade head                        # forward recovery OK
```

Introspection đã kiểm: `tutor_tool_calls` 10 cột (không có cột nội dung/args thô), FK
`users`/`courses`/`tutor_messages` (`ON DELETE CASCADE`), index `(message_id)`, `created_at`,
`user_id`, `course_id`.

### Dữ liệu cũ vẫn đọc được (đã kiểm chứng)

Seed thread + assistant message `completed` + 1 audit row ở revision 0009 → `downgrade 0009` (audit
biến mất) → `upgrade head` → `tutor_messages.content/status` giữ nguyên ⇒ **không mất dữ liệu hội thoại**.

### Race test (PostgreSQL throwaway `p31b_race_check`)

```bash
POSTGRES_TEST_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p31b_race_check"   python -m pytest tests/test_p31_tutor_postgres_concurrency.py -q     # 5 passed
```

### Giới hạn rollback

- `downgrade` mất **audit tool**. Thread/message/usage/allowance không bị đụng.
- DB dev `ailp` đã backup (`backup_pre_p31b_20261031_142709.sql`) trước upgrade.

## P4.0 — `0011_p40_source_ingest` (2026-10-31)

Expand-only: 2 bảng mới (`source_documents`, `source_chunks`), enum `source_document_status`,
index. Không sửa cột/bảng cũ. Ứng dụng tự chạy `alembic upgrade head` trong entrypoint container.

**Trước khi upgrade (bắt buộc với DB thật):**

```bash
docker compose exec db pg_dump -U ailp ailp > backup_pre_p40_$(date +%Y%m%d_%H%M%S).sql
grep -c "^COPY" backup_pre_p40_*.sql   # phải > 0
```

**Kiểm chứng đã chạy trên DB throwaway `p40_migration_check`:**

```bash
docker compose exec db psql -U ailp -d postgres -c "CREATE DATABASE p40_migration_check;"
cd backend
DATABASE_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p40_migration_check \
  python -m alembic upgrade 0010_p31_tutor_tools
# seed user + source (dữ liệu P3.0)
DATABASE_URL=…/p40_migration_check python -m alembic upgrade head
DATABASE_URL=…/p40_migration_check python -m alembic downgrade 0010_p31_tutor_tools
docker compose exec db psql -U ailp -d postgres -c "DROP DATABASE p40_migration_check;"
```

Kết quả ghi nhận: upgrade → `0011_p40_source_ingest`, 21 cột `source_documents`, user/source cũ còn
nguyên; downgrade → 2 bảng + enum biến mất, `sources`/`users` không đổi; upgrade lại thành công.

**Downgrade làm mất** trạng thái ingest + text đã trích (không khôi phục từ schema). Object gốc trong
MinIO vẫn còn nhưng không còn bản ghi tham chiếu — dọn thủ công nếu cần.

## P4.1 — `0012_p41_rag` (2026-10-31)

Expand-only: 1 bảng mới (`source_chunk_embeddings`), 1 cột nullable
(`tutor_messages.citations`), 2 index btree, **1 GIN index biểu thức** chỉ trên PostgreSQL
(`to_tsvector('simple', text)` cho lexical retrieval). Không sửa cột/bảng cũ, không cần
extension `pgvector` (vector lưu JSON — xem `docs/specs/20-P41-HYBRID-RAG.md`).

**Trước khi upgrade (bắt buộc với DB thật):**

```bash
docker compose exec db pg_dump -U ailp ailp > backup_pre_p41_$(date +%Y%m%d_%H%M%S).sql
grep -c "^COPY" backup_pre_p41_*.sql   # phải > 0
```

**Kiểm chứng đã chạy trên DB throwaway `p41_migration_check`:**

```bash
docker compose exec db psql -U ailp -d postgres -c "CREATE DATABASE p41_migration_check;"
cd backend
DATABASE_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p41_migration_check \
  python -m alembic upgrade 0011_p40_source_ingest
# seed 1 user + 1 source (dữ liệu cũ)
DATABASE_URL=…/p41_migration_check python -m alembic upgrade head
DATABASE_URL=…/p41_migration_check python -m alembic downgrade 0011_p40_source_ingest
DATABASE_URL=…/p41_migration_check python -m alembic upgrade head
docker compose exec db psql -U ailp -d postgres -c "DROP DATABASE p41_migration_check;"
```

Kết quả ghi nhận: `0012_p41_rag (head)`; `source_chunk_embeddings` 11 cột + UNIQUE spec +
2 FK CASCADE; `ix_source_chunks_fts_simple` là GIN `to_tsvector('simple', text)`;
`tutor_messages.citations` = jsonb nullable. Downgrade xóa GIN index + bảng + cột, `users`/
`sources` còn nguyên (1/1); upgrade lại thành công.

**Downgrade làm mất** vector đã tính và citation đã lưu. Nội dung gốc (`sources`,
`source_documents`, `source_chunks`, `tutor_messages.content`) **không** bị đụng; re-embed chạy
lại được qua `app.worker.ingest.reconcile_embeddings` nhưng có chi phí nếu dùng provider thật.

**Lưu ý vận hành:** thêm GIN index trên bảng lớn sẽ khóa ghi trong lúc build. Với DB có nhiều
chunk, chạy ngoài giờ cao điểm hoặc đổi sang `CREATE INDEX CONCURRENTLY` thủ công trước khi
`alembic upgrade head`.
