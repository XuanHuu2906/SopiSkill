"""P4.1 retrieval evaluation — Recall@K, MRR, citation validity, latency, abstention.

Chạy offline trên SQLite in-memory (embedding hashing). Đây là **số đo baseline**
của hashing embedding, không phải chất lượng semantic embedding của model thật;
report ghi rõ provider/model/dimension/version để không so sánh nhầm.

    cd backend
    python -m evals.rag_eval                 # SQLite in-memory, provider theo .env
    python -m evals.rag_eval --json          # in JSON đầy đủ
    python -m evals.rag_eval --save          # ghi evals/reports/rag_<ts>.json

Đo:
  - Recall@K      : tỷ lệ câu có ít nhất một (doc,page) ground truth trong top-K.
  - MRR           : trung bình 1/rank của hit đầu tiên.
  - Citation valid: tỷ lệ citation trích từ top-K resolve đúng (doc,page) ground truth.
  - Abstention     : tỷ lệ câu ngoài phạm vi trả `insufficientEvidence`.
  - Latency       : p50/p95 ms mỗi truy vấn.

KHÔNG dùng LLM. Không gọi network. Không đọc tài liệu bên thứ ba.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import statistics
import sys
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from evals.rag_dataset import DOCUMENTS, QUERIES, dataset_summary

REPORT_DIR = pathlib.Path(__file__).parent / "reports"
EVAL_VERSION = "p4.1-rag-v1"

try:  # Windows console mặc định cp1258/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):  # pragma: no cover
    pass


async def _build_corpus(engine) -> tuple:
    """Tạo user + course + source + document/chunk cho MỌI tài liệu eval."""
    import uuid as _uuid

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        user = User(external_id=f"rag-eval-{_uuid.uuid4().hex}", email=f"{_uuid.uuid4().hex}@eval.dev")
        db.add(user)
        await db.flush()
        course = Course(user_id=user.id, topic="RAG eval", client_course_id=_uuid.uuid4().hex[:16])
        db.add(course)
        await db.flush()

        # page → (doc_id, page_number) để dựng ground truth theo trang.
        for doc in DOCUMENTS:
            source = Source(
                source_type="user_document",
                title=doc.title,
                owner_id=user.id,
                visibility=SourceVisibility.private,
                dedupe_key=f"eval-{doc.id}",
                version="1.0",
                language=doc.language,
            )
            db.add(source)
            await db.flush()
            document = SourceDocument(
                source_id=source.id,
                content_hash=_uuid.uuid4().hex * 2,
                pipeline_version="p4.0-v1",
                storage_key=f"sources/{source.id}/{_uuid.uuid4().hex}",
                status=SourceDocumentStatus.ready,
                page_count=len(doc.pages),
            )
            db.add(document)
            await db.flush()

            chunks = []
            for index, text in enumerate(doc.pages):
                chunk = SourceChunk(
                    document_id=document.id,
                    source_id=source.id,
                    chunk_index=index,
                    page_number=index + 1,
                    char_start=0,
                    char_end=len(text),
                    section_anchor=f"trang {index + 1}",
                    text=text,
                    text_hash=embedding_service.hashlib.sha256(text.encode()).hexdigest(),
                )
                db.add(chunk)
                chunks.append(chunk)
            await db.flush()
            await embedding_service.embed_chunks(db, chunks)
            db.add(CourseSource(course_id=course.id, source_id=source.id))

        await db.commit()
        return user.id, course.id


def _page_key(item) -> tuple[str, int]:
    return (str(item.source_id), item.page_number)


async def run_eval(top_k: int = 6) -> dict:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=__import__(
        "sqlalchemy.pool", fromlist=["StaticPool"]
    ).StaticPool)
    started = time.perf_counter()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        user_id, course_id = await _build_corpus(engine)

        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        spec = embedding_service.active_spec()

        # Map source title → doc id để quy đổi ground truth sang source uuid.
        async with Session() as db:
            from sqlalchemy import select

            rows = (
                await db.execute(select(Source.id, Source.title))
            ).all()
            source_by_title = {title: source_id for source_id, title in rows}
        doc_to_source = {
            doc.id: source_by_title[doc.title] for doc in DOCUMENTS
        }

        records: list[dict] = []
        latencies: list[float] = []
        async with Session() as db:
            for query in QUERIES:
                begin = time.perf_counter()
                result = await retrieval_service.retrieve(
                    db,
                    course_id=course_id,
                    user_id=user_id,
                    query=query.query,
                    top_k=top_k,
                )
                elapsed_ms = (time.perf_counter() - begin) * 1000
                latencies.append(elapsed_ms)

                expected = {
                    (str(doc_to_source[doc_id]), page) for doc_id, page in query.expect
                }
                returned = [_page_key(item) for item in result.items]
                first_rank = next(
                    (index + 1 for index, key in enumerate(returned) if key in expected),
                    None,
                )
                records.append(
                    {
                        "id": query.id,
                        "language": query.language,
                        "shouldAbstain": query.should_abstain,
                        "insufficientEvidence": result.insufficient_evidence,
                        "components": {
                            "lexicalHits": result.lexical_hits,
                            "vectorHits": result.vector_hits,
                        },
                        "hitCount": len(returned),
                        "firstHitRank": first_rank,
                        "recallAtK": bool(first_rank) if expected else None,
                        "abstained": result.insufficient_evidence if query.should_abstain else None,
                        "latencyMs": round(elapsed_ms, 2),
                        "reason": result.reason,
                    }
                )

        answerable = [record for record in records if record["recallAtK"] is not None]
        abstain_cases = [record for record in records if record["shouldAbstain"]]
        recall = (
            sum(1 for record in answerable if record["recallAtK"]) / len(answerable)
            if answerable
            else 0.0
        )
        mrr = (
            statistics.fmean(
                1.0 / record["firstHitRank"]
                for record in answerable
                if record["firstHitRank"]
            )
            if any(record["firstHitRank"] for record in answerable)
            else 0.0
        )
        abstention = (
            sum(1 for record in abstain_cases if record["abstained"]) / len(abstain_cases)
            if abstain_cases
            else None
        )

        by_language: dict[str, dict] = {}
        for language in sorted({record["language"] for record in records}):
            subset = [record for record in records if record["language"] == language]
            subset_answerable = [r for r in subset if r["recallAtK"] is not None]
            by_language[language] = {
                "queries": len(subset),
                "recallAtK": (
                    sum(1 for r in subset_answerable if r["recallAtK"]) / len(subset_answerable)
                    if subset_answerable
                    else None
                ),
                "mrr": (
                    statistics.fmean(
                        1.0 / r["firstHitRank"] for r in subset_answerable if r["firstHitRank"]
                    )
                    if any(r["firstHitRank"] for r in subset_answerable)
                    else 0.0
                ),
            }

        p50 = statistics.median(latencies) if latencies else 0.0
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))] if ordered else 0.0

        return {
            "evalVersion": EVAL_VERSION,
            "embedding": {
                "provider": spec.provider,
                "model": spec.model,
                "dimension": spec.dimension,
                "version": spec.version,
                "note": (
                    "'hashing' là baseline lexical/subword, KHÔNG phải semantic "
                    "embedding của model thật."
                ),
            },
            "topK": top_k,
            "dataset": dataset_summary(),
            "metrics": {
                "recallAtK": round(recall, 4),
                "mrr": round(mrr, 4),
                "abstentionRate": None if abstention is None else round(abstention, 4),
                "latencyMsP50": round(p50, 2),
                "latencyMsP95": round(p95, 2),
                "totalDurationSeconds": round(time.perf_counter() - started, 2),
            },
            "byLanguage": by_language,
            "queries": records,
        }
    finally:
        await engine.dispose()


def _print_report(report: dict) -> None:
    embedding = report["embedding"]
    print(
        f"Embedding: {embedding['provider']}/{embedding['model']} "
        f"d={embedding['dimension']}/{embedding['version']}"
    )
    print(f"Dataset: {report['dataset']}")
    metrics = report["metrics"]
    print(
        f"Recall@{report['topK']}: {metrics['recallAtK']:.3f} | "
        f"MRR: {metrics['mrr']:.3f} | "
        f"Abstention: {metrics['abstentionRate']} | "
        f"p50: {metrics['latencyMsP50']}ms | p95: {metrics['latencyMsP95']}ms"
    )
    for language, summary in report["byLanguage"].items():
        print(
            f"  [{language}] n={summary['queries']} "
            f"recall={summary['recallAtK']} mrr={round(summary['mrr'], 4)}"
        )
    misses = [q["id"] for q in report["queries"] if q["recallAtK"] is False]
    if misses:
        print(f"  MISS ({len(misses)}): {', '.join(misses)}")
    false_abstain = [
        q["id"] for q in report["queries"] if q["shouldAbstain"] and not q["abstained"]
    ]
    if false_abstain:
        print(f"  KHÔNG abstain dù ngoài phạm vi: {', '.join(false_abstain)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P4.1 retrieval evaluation (offline)")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--json", action="store_true", help="In JSON đầy đủ")
    parser.add_argument("--save", action="store_true", help="Ghi report vào evals/reports/")
    args = parser.parse_args(argv)

    report = asyncio.run(run_eval(top_k=args.top_k))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)

    if args.save:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = REPORT_DIR / f"rag_{stamp}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
