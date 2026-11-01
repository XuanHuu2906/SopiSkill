"""P4.2 real-network E2E (chạy tay, KHÔNG thuộc pytest suite).

Mục đích: chứng minh đường API thật hoạt động với mạng thật (example.com + arXiv),
bao gồm rights audit, ingest worker, chunk provenance và citation `sourceUrl`.

Không chạm DB chính: dùng SQLite file throwaway trong thư mục temp.

Chạy:
  cd backend
  python scripts/p42_real_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile
import uuid

TMP_DB = pathlib.Path(tempfile.gettempdir()) / f"p42_real_e2e_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TMP_DB.as_posix()}"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["REDIS_URL"] = ""
os.environ["JWT_SECRET"] = "p42-e2e-local-only-not-production-secret"
os.environ["ALLOW_DEMO_HEADER"] = "false"
os.environ["GENERATION_INLINE_BLOCKING"] = "true"
os.environ["SOURCE_STORAGE_BACKEND"] = "memory"
os.environ["SOURCE_STORAGE_BUCKET"] = "e2e-sources"
os.environ["WEB_INGEST_ENABLED"] = "true"
os.environ["WEB_INGEST_ALLOWED_HOSTS"] = "example.com,arxiv.org,export.arxiv.org"
os.environ["WEB_INGEST_RESPECT_ROBOTS"] = "true"
os.environ["EMBEDDING_ENABLED"] = "true"
os.environ["RAG_ENABLED"] = "true"
os.environ["ENV"] = "development"
# Đảm bảo chạy từ backend/ để import app
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PASSWORD = "Passw0rd!123"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def main() -> int:
    from httpx import ASGITransport, AsyncClient

    from app.db.session import create_all, SessionLocal
    from app.main import app

    await create_all()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
        email = f"p42-e2e-{uuid.uuid4().hex[:8]}@test.dev"
        reg = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
        check("register", reg.status_code == 201, f"HTTP {reg.status_code}")

        cfg = await client.get("/v1/sources/ingest-config")
        conf = cfg.json()
        check("ingest-config webEnabled", conf.get("webEnabled") is True, str(conf.get("webEnabled")))
        check("ingest-config arxivEnabled", conf.get("arxivEnabled") is True, str(conf.get("arxivEnabled")))
        check("ingest-config respectRobots", conf.get("webRespectRobots") is True)

        # ---- nguồn web thật (example.com) ----
        src = await client.post(
            "/v1/sources",
            json={
                "sourceType": "webpage",
                "title": "Example Domain (real network)",
                "visibility": "private",
                "language": "en",
            },
            headers=csrf(client),
        )
        check("create source web", src.status_code == 201, f"HTTP {src.status_code}")
        web_source_id = src.json()["id"]

        no_rights = await client.post(
            f"/v1/sources/{web_source_id}/web-document",
            json={"url": "https://example.com/"},
            headers=csrf(client),
        )
        check("rights required (422)", no_rights.status_code == 422, f"HTTP {no_rights.status_code}")

        web_doc = await client.post(
            f"/v1/sources/{web_source_id}/web-document",
            json={"url": "https://example.com/", "userConfirmedRights": True},
            headers=csrf(client),
        )
        check("ingest example.com", web_doc.status_code == 202, f"HTTP {web_doc.status_code} {web_doc.text[:160]}")
        web_body = web_doc.json() if web_doc.status_code == 202 else {}
        check("web origin", web_body.get("origin") == "web", str(web_body.get("origin")))
        check("web status ready", web_body.get("status") == "ready", str(web_body.get("status")))
        check("web chunkCount>0", (web_body.get("chunkCount") or 0) > 0, str(web_body.get("chunkCount")))
        check("web rightsConfirmed", web_body.get("rightsConfirmed") is True)
        check(
            "web originUrl",
            web_body.get("originUrl") == "https://example.com/",
            str(web_body.get("originUrl")),
        )

        # idempotent re-fetch
        again = await client.post(
            f"/v1/sources/{web_source_id}/web-document",
            json={"url": "https://example.com/", "userConfirmedRights": True},
            headers=csrf(client),
        )
        check(
            "web ingest idempotent",
            again.status_code == 202 and again.json().get("id") == web_body.get("id"),
            f"HTTP {again.status_code}",
        )

        # ---- nguồn arXiv thật ----
        arx_src = await client.post(
            "/v1/sources",
            json={
                "sourceType": "academic",
                "title": "Attention Is All You Need (real arXiv)",
                "visibility": "private",
                "language": "en",
            },
            headers=csrf(client),
        )
        check("create source arxiv", arx_src.status_code == 201, f"HTTP {arx_src.status_code}")
        arx_source_id = arx_src.json()["id"]

        arx_doc = await client.post(
            f"/v1/sources/{arx_source_id}/web-document",
            json={"arxivId": "1706.03762", "userConfirmedRights": True},
            headers=csrf(client),
        )
        check("ingest arxiv 1706.03762", arx_doc.status_code == 202, f"HTTP {arx_doc.status_code} {arx_doc.text[:200]}")
        arx_body = arx_doc.json() if arx_doc.status_code == 202 else {}
        check("arxiv origin", arx_body.get("origin") == "arxiv", str(arx_body.get("origin")))
        check("arxiv status ready", arx_body.get("status") == "ready", str(arx_body.get("status")))
        check("arxiv pages>=10", (arx_body.get("pageCount") or 0) >= 10, str(arx_body.get("pageCount")))
        check("arxiv chunkCount>0", (arx_body.get("chunkCount") or 0) > 0, str(arx_body.get("chunkCount")))

        src_detail = await client.get(f"/v1/sources/{arx_source_id}")
        meta = src_detail.json()
        check("arxiv publisher", meta.get("publisher") == "arXiv", str(meta.get("publisher")))
        check(
            "arxiv canonicalUrl",
            meta.get("canonicalUrl") == "https://arxiv.org/abs/1706.03762",
            str(meta.get("canonicalUrl")),
        )
        check(
            "arxiv still unverified",
            meta.get("verificationStatus") == "unverified",
            str(meta.get("verificationStatus")),
        )

        # ---- citation sourceUrl qua retrieval thật ----
        from sqlalchemy import select

        from app.models import Course, CourseSource, SourceChunk, SourceDocument
        from app.services import embedding_service, retrieval_service

        me = await client.get("/v1/auth/me")
        user_id = uuid.UUID(me.json()["id"].removeprefix("usr_"))

        async with SessionLocal() as db:
            course = Course(user_id=user_id, topic="Transformer", client_course_id=uuid.uuid4().hex[:16])
            db.add(course)
            await db.flush()
            for sid in (web_source_id, arx_source_id):
                db.add(
                    CourseSource(
                        course_id=course.id,
                        source_id=uuid.UUID(sid.removeprefix("src_")),
                        evaluation=None,
                    )
                )
            await db.commit()
            course_id = course.id
            chunks = list((await db.execute(select(SourceChunk))).scalars().all())
            await embedding_service.embed_chunks(db, chunks)
            await db.commit()

        async with SessionLocal() as db:
            result = await retrieval_service.retrieve(
                db,
                course_id=course_id,
                user_id=user_id,
                query="attention is all you need transformer",
                source_ids=None,
                top_k=5,
            )
        check("retrieval returns items", bool(result.items), f"{len(result.items)} items")
        urls = {item.source_url for item in result.items}
        check("retrieved chunks carry sourceUrl", all(urls), str(list(urls))[:200])

        from app.services import citation_service

        if result.items:
            citations, rejected = citation_service.verify_answer_citations(
                " ".join(f"[chk_{item.chunk_id}]" for item in result.items[:2]),
                retrieved=result.items,
            )
            check("citations verified", bool(citations), f"{len(citations)} citations, rejected={len(rejected)}")
            check(
                "citation has real sourceUrl",
                all(c.get("sourceUrl") for c in citations),
                str([c.get("sourceUrl") for c in citations])[:200],
            )
            check(
                "evidenceSupported stays false",
                all(c.get("evidenceSupported") is False for c in citations),
            )

        # ---- cross-user isolation ----
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as other:
            await other.post(
                "/v1/auth/register",
                json={"email": f"p42-e2e-b-{uuid.uuid4().hex[:8]}@test.dev", "password": PASSWORD},
            )
            denied = await other.post(
                f"/v1/sources/{web_source_id}/web-document",
                json={"url": "https://example.com/", "userConfirmedRights": True},
                headers=csrf(other),
            )
            check("cross-user ingest 404", denied.status_code == 404, f"HTTP {denied.status_code}")
            denied_del = await other.delete(f"/v1/sources/{web_source_id}", headers=csrf(other))
            check("cross-user delete 404", denied_del.status_code == 404, f"HTTP {denied_del.status_code}")

        # ---- SSRF thật: chặn ngay cả khi cờ bật ----
        from app.core.limits import clear_rate_limits

        clear_rate_limits()  # rate limit per-user 5/60s không được che mất kết quả SSRF
        local_src = await client.post(
            "/v1/sources",
            json={
                "sourceType": "webpage",
                "title": "SSRF probe",
                "visibility": "private",
            },
            headers=csrf(client),
        )
        local_src_id = local_src.json()["id"]
        clear_rate_limits()
        for target, expect_codes in (
            ("http://169.254.169.254/latest/meta-data/", {403, 422}),
            ("https://169.254.169.254/latest/meta-data/", {403, 422}),
            ("http://127.0.0.1:8000/v1/auth/me", {403, 422}),
            ("https://evil.invalid/", {403}),
        ):
            resp = await client.post(
                f"/v1/sources/{local_src_id}/web-document",
                json={"url": target, "userConfirmedRights": True},
                headers=csrf(client),
            )
            check(
                f"blocked {target}",
                resp.status_code in expect_codes,
                f"HTTP {resp.status_code} {resp.json().get('detail', {}).get('code') if resp.headers.get('content-type','').startswith('application/json') else ''}",
            )

    ok = all(item[1] for item in RESULTS)
    print("\n=== SUMMARY ===")
    for name, passed, detail in RESULTS:
        print(f"{'PASS' if passed else 'FAIL'}\t{name}\t{detail}")
    print(f"\n{sum(1 for r in RESULTS if r[1])}/{len(RESULTS)} checks passed")
    try:
        TMP_DB.unlink(missing_ok=True)
    except OSError:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
