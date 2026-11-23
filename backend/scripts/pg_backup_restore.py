#!/usr/bin/env python3
"""OPS-007 — PostgreSQL Backup, Integrity Verify & Isolated Restore Drill CLI.

Nguyên tắc an toàn:
  - Không bao giờ in hay ghi password/DSN vào stdout, stderr, hay file metadata.
  - Luôn dùng `PGPASSWORD` qua env của tiến trình con, không truyền qua argv.
  - `restore-drill` mặc định TỪ CHỐI ghi đè DB đích trừ khi tên DB chứa
    `drill` / `restore` / `scratch` / `test` (hoặc truyền tường minh
    `--i-know-this-overwrites-target`).
  - Mọi lệnh chạy `subprocess.run(..., shell=False)` với danh sách tham số tường minh.

Cách dùng:
  python backend/scripts/pg_backup_restore.py backup --output-dir ./backups
  python backend/scripts/pg_backup_restore.py verify --backup ./backups/sopiskill_...dump
  python backend/scripts/pg_backup_restore.py restore-drill \\
      --backup ./backups/sopiskill_...dump --target-db ailp_restore_drill
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

PG_CUSTOM_MAGIC = b"PGDMP"
SAFE_DRILL_TOKENS = ("drill", "restore", "scratch", "test")
_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$")
_CORE_TABLES = ("alembic_version", "users", "courses", "lessons")


def parse_pg_connection(
    *,
    database_url: str | None = None,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    dbname: str | None = None,
) -> dict[str, str]:
    """Parse PostgreSQL connection settings from explicit args, DATABASE_URL, or POSTGRES_* env."""
    parsed_host = host or os.environ.get("POSTGRES_HOST", "localhost")
    parsed_port = str(port or os.environ.get("POSTGRES_PORT", "5432"))
    parsed_user = user or os.environ.get("POSTGRES_USER", "ailp")
    parsed_password = password if password is not None else os.environ.get("POSTGRES_PASSWORD", "")
    parsed_db = dbname or os.environ.get("POSTGRES_DB", "ailp")

    raw_url = database_url or os.environ.get("DATABASE_URL", "")
    if raw_url and raw_url.startswith("postgresql"):
        # Normalize SQLAlchemy driver prefix e.g. postgresql+asyncpg:// -> postgresql://
        normalized = re.sub(r"^postgresql\+[a-z0-9_]+://", "postgresql://", raw_url)
        u = urlparse(normalized)
        if not host and u.hostname:
            parsed_host = u.hostname
        if not port and u.port:
            parsed_port = str(u.port)
        if not user and u.username:
            parsed_user = u.username
        if password is None and u.password is not None:
            parsed_password = u.password
        if not dbname and u.path and u.path.strip("/"):
            parsed_db = u.path.strip("/")

    return {
        "host": parsed_host,
        "port": parsed_port,
        "user": parsed_user,
        "password": parsed_password,
        "dbname": parsed_db,
    }


def validate_db_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not _DB_NAME_RE.match(cleaned):
        raise ValueError(f"Tên database không hợp lệ: {name!r}")
    return cleaned


def is_safe_drill_target(target_db: str, *, allow_unsafe: bool = False) -> bool:
    """Chặn restore nhầm vào DB chính trừ khi tên chứa từ khóa scratch/drill hoặc có cờ ép."""
    if allow_unsafe:
        return True
    lowered = target_db.lower()
    return any(token in lowered for token in SAFE_DRILL_TOKENS)


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def checksum_path_for(backup_path: Path) -> Path:
    return Path(f"{backup_path}.sha256")


def meta_path_for(backup_path: Path) -> Path:
    return Path(f"{backup_path}.meta.json")


def write_backup_artifacts(backup_path: Path, *, dbname: str) -> dict:
    """Write .sha256 and sanitized .meta.json next to a backup dump (ZERO secrets)."""
    digest = compute_sha256(backup_path)
    checksum_path_for(backup_path).write_text(f"{digest}  {backup_path.name}\n", encoding="utf-8")
    meta = {
        "file": backup_path.name,
        "database": dbname,
        "sizeBytes": backup_path.stat().st_size,
        "sha256": digest,
        "createdAtUtc": datetime.now(UTC).isoformat(),
        "format": "pg_dump_custom",
    }
    meta_path_for(backup_path).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def verify_backup_file(backup_path: Path) -> dict:
    """Verify dump file exists, starts with PGDMP magic bytes, and matches .sha256."""
    if not backup_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file backup: {backup_path}")
    with backup_path.open("rb") as fh:
        magic = fh.read(len(PG_CUSTOM_MAGIC))
    if magic != PG_CUSTOM_MAGIC:
        raise ValueError("File backup không đúng định dạng pg_dump custom (thiếu header PGDMP).")

    actual_sha = compute_sha256(backup_path)
    sha_file = checksum_path_for(backup_path)
    expected_sha: str | None = None
    if sha_file.is_file():
        first_line = sha_file.read_text(encoding="utf-8").strip().splitlines()[0]
        expected_sha = first_line.split()[0].strip().lower()
        if expected_sha != actual_sha.lower():
            raise ValueError(
                f"Checksum SHA-256 không khớp (expected={expected_sha[:12]}..., actual={actual_sha[:12]}...)."
            )

    return {
        "ok": True,
        "file": str(backup_path),
        "sizeBytes": backup_path.stat().st_size,
        "sha256": actual_sha,
        "checksumFileVerified": expected_sha is not None,
    }


def _pg_env(password: str) -> dict[str, str]:
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    return env


def build_pg_dump_cmd(conn: dict[str, str], output_file: Path) -> list[str]:
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "-h",
        conn["host"],
        "-p",
        conn["port"],
        "-U",
        conn["user"],
        "-d",
        conn["dbname"],
        "-f",
        str(output_file),
    ]


def build_pg_restore_cmd(conn: dict[str, str], target_db: str, backup_file: Path) -> list[str]:
    return [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "-h",
        conn["host"],
        "-p",
        conn["port"],
        "-U",
        conn["user"],
        "-d",
        target_db,
        str(backup_file),
    ]


def build_psql_verify_cmd(conn: dict[str, str], target_db: str) -> list[str]:
    sql = (
        "SELECT "
        "(SELECT version_num FROM alembic_version LIMIT 1) AS alembic_head, "
        "(SELECT count(*) FROM information_schema.tables WHERE table_schema='public') AS table_count, "
        "(SELECT count(*) FROM users) AS users_count, "
        "(SELECT count(*) FROM courses) AS courses_count, "
        "(SELECT count(*) FROM lessons) AS lessons_count;"
    )
    return [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-At",
        "-F",
        "|",
        "-h",
        conn["host"],
        "-p",
        conn["port"],
        "-U",
        conn["user"],
        "-d",
        target_db,
        "-c",
        sql,
    ]


def cmd_backup(args: argparse.Namespace) -> int:
    conn = parse_pg_connection(
        database_url=args.database_url,
        host=args.host,
        port=args.port,
        user=args.user,
        dbname=args.dbname,
    )
    dbname = validate_db_name(conn["dbname"])
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"{dbname}_{stamp}.dump"

    cmd = build_pg_dump_cmd(conn, out_file)
    proc = subprocess.run(cmd, env=_pg_env(conn["password"]), capture_output=True, text=True)
    if proc.returncode != 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "step": "pg_dump",
                    "returncode": proc.returncode,
                    "error": (proc.stderr or "").strip()[:400],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return proc.returncode

    meta = write_backup_artifacts(out_file, dbname=dbname)
    print(json.dumps({"ok": True, "backup": str(out_file), "meta": meta}, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    result = verify_backup_file(Path(args.backup))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_restore_drill(args: argparse.Namespace) -> int:
    target_db = validate_db_name(args.target_db)
    if not is_safe_drill_target(target_db, allow_unsafe=args.i_know_this_overwrites_target):
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "UNSAFE_RESTORE_TARGET",
                    "message": (
                        f"Từ chối restore vào DB '{target_db}'. Tên DB diễn tập phải chứa một trong "
                        f"{SAFE_DRILL_TOKENS} (hoặc truyền --i-know-this-overwrites-target)."
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    backup_path = Path(args.backup)
    verified = verify_backup_file(backup_path)
    conn = parse_pg_connection(
        database_url=args.database_url,
        host=args.host,
        port=args.port,
        user=args.user,
        dbname=target_db,
    )
    env = _pg_env(conn["password"])

    restore_cmd = build_pg_restore_cmd(conn, target_db, backup_path)
    r_proc = subprocess.run(restore_cmd, env=env, capture_output=True, text=True)
    if r_proc.returncode != 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "step": "pg_restore",
                    "returncode": r_proc.returncode,
                    "error": (r_proc.stderr or "").strip()[:400],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return r_proc.returncode

    verify_cmd = build_psql_verify_cmd(conn, target_db)
    v_proc = subprocess.run(verify_cmd, env=env, capture_output=True, text=True)
    if v_proc.returncode != 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "step": "psql_verify",
                    "returncode": v_proc.returncode,
                    "error": (v_proc.stderr or "").strip()[:400],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return v_proc.returncode

    parts = (v_proc.stdout or "").strip().split("|")
    summary = {
        "ok": True,
        "targetDb": target_db,
        "backupVerified": verified,
        "alembicHead": parts[0] if len(parts) > 0 else None,
        "tableCount": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
        "usersCount": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None,
        "coursesCount": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
        "lessonsCount": int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None,
        "drilledAtUtc": datetime.now(UTC).isoformat(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SopiSkill PostgreSQL backup & restore drill CLI")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--database-url", default=None)
    common.add_argument("--host", default=None)
    common.add_argument("--port", type=int, default=None)
    common.add_argument("--user", default=None)
    common.add_argument("--dbname", default=None)

    sub = parser.add_subparsers(dest="command", required=True)

    p_bak = sub.add_parser("backup", parents=[common], help="Tạo bản backup pg_dump custom + sha256")
    p_bak.add_argument("--output-dir", default="./backups")
    p_bak.set_defaults(func=cmd_backup)

    p_ver = sub.add_parser("verify", help="Kiểm tra header PGDMP và checksum SHA-256")
    p_ver.add_argument("--backup", required=True)
    p_ver.set_defaults(func=cmd_verify)

    p_drill = sub.add_parser(
        "restore-drill",
        parents=[common],
        help="Diễn tập khôi phục vào DB tách biệt và kiểm tra schema/bảng cốt lõi",
    )
    p_drill.add_argument("--backup", required=True)
    p_drill.add_argument("--target-db", required=True)
    p_drill.add_argument(
        "--i-know-this-overwrites-target",
        action="store_true",
        help="Cho phép restore vào DB đích không có từ khóa drill/restore/scratch/test",
    )
    p_drill.set_defaults(func=cmd_restore_drill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
