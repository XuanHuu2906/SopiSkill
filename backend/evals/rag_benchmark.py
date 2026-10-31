"""P4.1 benchmark — quyết định có cần pgvector/ANN hay chưa (bằng số đo).

Chạy:

    cd backend
    python -m evals.rag_benchmark --sizes 500,2000,8000

Đo, ở từng kích thước corpus (synthetic, sinh xác định từ `rag_dataset`):
  - thời gian nạp candidate + cosine exact (nhánh vector),
  - lexical (token-overlap / FTS path),
  - tổng latency retrieval top-6,
  - bộ nhớ vector ước tính.

Kết luận KHÔNG được hard-code "đủ tốt": script in số đo và ngưỡng quyết định
(`--budget-ms`, mặc định 150ms p95). Chuyển sang pgvector chỉ khi vượt ngưỡng
này trên corpus thật — xem `docs/specs/20-P41-HYBRID-RAG.md` mục 7.

Không gọi network, không gọi LLM, không dùng dữ liệu bên thứ ba.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import statistics
import sys
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    Course,
    CourseSource,
    Source,
    SourceChunk,
    SourceDocument,
    SourceDocumentStatus,
    SourceVisibility,
    User,
)
from app.services import embedding_service, retrieval_service
from evals.rag_dataset import DOCUMENTS, QUERIES

REPORT_DIR = pathlib.Path(__file__).parent / "reports"
BENCHMARK_VERSION = "p4.1-bench-v1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):  # pragma: no cover
    pass


def _synth_pages(count: int) -> list[str]:
    """Sinh trang tổng hợp từ văn bản eval (không phải tài liệu bên thứ ba)."""
    base = [page for doc in DOCUMENTS for page in doc.pages]
    pages: list[str] = []
    index = 0
    while len(pages) < count:
        seed = base[index % len(base)]
        # Biến thể nhẹ để không trùng hash tuyệt đối nhưng cùng phân bố từ vựng.
        pages.append(f"[{index // len(base)}] {seed}")
        index += 1
    return pages


async def _bench_once(size: int, queries: int, top_k: int) -> dict:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        load_started = time.perf_counter()
        async with Session() as db:
            user = User(external_id=f"bench-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@b.dev")
            db.add(user)
            await db.flush()
            course = Course(
                user_id=user.id, topic="bench", client_course_id=uuid.uuid4().hex[:16]
            )
            db.add(course)
            await db.flush()

            pages = _synth_pages(size)
            chunk_size = 25
            for group_start in range(0, len(pages), chunk_size):
                group = pages[group_start : group_start + chunk_size]
                source = Source(
                    source_type="user_document",
                    title=f"Nguồn {group_start}",
                    owner_id=user.id,
                    visibility=SourceVisibility.private,
                    dedupe_key=f"bench-{group_start}",
                )
                db.add(source)
                await db.flush()
                document = SourceDocument(
                    source_id=source.id,
                    content_hash=uuid.uuid4().hex * 2,
                    pipeline_version="p4.0-v1",
                    storage_key=f"sources/{source.id}/{uuid.uuid4().hex}",
                    status=SourceDocumentStatus.ready,
                    page_count=len(group),
                )
                db.add(document)
                await db.flush()
                chunks = []
                for index, text in enumerate(group):
                    chunk = SourceChunk(
                        document_id=document.id,
                        source_id=source.id,
                        chunk_index=index,
                        page_number=index + 1,
                        char_start=0,
                        char_end=len(text),
                        text=text,
                        text_hash=embedding_service.hashlib.sha256(
                            text.encode()
                        ).hexdigest(),
                    )
                    db.add(chunk)
                    chunks.append(chunk)
                await db.flush()
                await embedding_service.embed_chunks(db, chunks)
                db.add(CourseSource(course_id=course.id, source_id=source.id))
            await db.commit()
            load_seconds = time.perf_counter() - load_started
            user_id, course_id = user.id, course.id

        latencies: list[float] = []
        vector_counts: list[int] = []
        async with Session() as db:
            for query in list(QUERIES)[:queries]:
                begin = time.perf_counter()
                result = await retrieval_service.retrieve(
                    db,
                    course_id=course_id,
                    user_id=user_id,
                    query=query.query,
                    top_k=top_k,
                )
                latencies.append((time.perf_counter() - begin) * 1000)
                vector_counts.append(result.vector_hits)

            spec = embedding_service.active_spec()
            # Ước tính bộ nhớ vector: dimension * 8 byte (double) + overhead JSON.
            vector_bytes = (
                (await db.execute(select(SourceChunk.id))).scalars().all()
            )
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
        return {
            "size": size,
            "sources": (size + chunk_size - 1) // chunk_size,
            "loadSeconds": round(load_seconds, 2),
            "queries": len(latencies),
            "latencyMsP50": round(statistics.median(latencies), 2),
            "latencyMsP95": round(p95, 2),
            "latencyMsMax": round(max(latencies), 2),
            "avgVectorHits": round(statistics.fmean(vector_counts), 1) if vector_counts else 0,
            "estimatedVectorMb": round(
                len(vector_bytes) * spec.dimension * 8 / (1024 * 1024), 2
            ),
        }
    finally:
        await engine.dispose()


async def run_benchmark(sizes: list[int], queries: int, top_k: int) -> dict:
    results = []
    for size in sizes:
        print(f"  đang đo size={size} ...")
        results.append(await _bench_once(size, queries, top_k))
    return {
        "benchmarkVersion": BENCHMARK_VERSION,
        "embedding": {
            "provider": embedding_service.active_spec().provider,
            "model": embedding_service.active_spec().model,
            "dimension": embedding_service.active_spec().dimension,
            "version": embedding_service.active_spec().version,
            "note": "hashing baseline; vector scan JSON exact (không ANN).",
        },
        "topK": top_k,
        "results": results,
    }


def decide(report: dict, budget_ms: float, limit: int) -> dict:
    """Quy tắc go/no-go dựa trên số đo, không dựa trên cảm giác."""
    results = report["results"]
    worst = max(results, key=lambda item: item["latencyMsP95"])
    over_budget = [item["size"] for item in results if item["latencyMsP95"] > budget_ms]
    over_limit = [item["size"] for item in results if item["size"] > limit]
    return {
        "budgetMsP95": budget_ms,
        "candidateLimit": limit,
        "worstP95": worst["latencyMsP95"],
        "worstSize": worst["size"],
        "sizesOverBudget": over_budget,
        "sizesOverCandidateLimit": over_limit,
        "needPgvector": bool(over_budget) or bool(over_limit),
        "rationale": (
            "Cần pgvector/ANN khi p95 vượt ngân sách hoặc corpus vượt trần candidate "
            "exact-scan hiện tại. Không chuyển chỉ vì 'nghe hiện đại hơn'."
        ),
    }


def _print_report(report: dict, decision: dict) -> None:
    print(
        f"Embedding: {report['embedding']['provider']}/{report['embedding']['model']} "
        f"d={report['embedding']['dimension']}"
    )
    print(f"{'size':>7} {'p50ms':>8} {'p95ms':>8} {'maxms':>8} {'vecMB':>7}")
    for row in report["results"]:
        print(
            f"{row['size']:>7} {row['latencyMsP50']:>8} {row['latencyMsP95']:>8} "
            f"{row['latencyMsMax']:>8} {row['estimatedVectorMb']:>7}"
        )
    print(
        f"Decision: needPgvector={decision['needPgvector']} "
        f"(worst p95={decision['worstP95']}ms @ size={decision['worstSize']}, "
        f"budget={decision['budgetMsP95']}ms, candidateLimit={decision['candidateLimit']})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P4.1 retrieval scale benchmark")
    parser.add_argument("--sizes", default="500,2000,8000")
    parser.add_argument("--queries", type=int, default=16)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--budget-ms", type=float, default=150.0)
    parser.add_argument("--candidate-limit", type=int, default=2000)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)

    sizes = [int(value) for value in args.sizes.split(",") if value.strip()]
    report = asyncio.run(run_benchmark(sizes, args.queries, args.top_k))
    decision = decide(report, args.budget_ms, args.candidate_limit)
    report["decision"] = decision

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report, decision)

    if args.save:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = REPORT_DIR / f"rag_bench_{stamp}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
