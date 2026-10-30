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
