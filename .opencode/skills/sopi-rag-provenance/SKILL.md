---
name: sopi-rag-provenance
description: Use when implementing SopiSkill PDF/web/arXiv ingestion, text chunks, embeddings, PostgreSQL pgvector retrieval, hybrid search and verifiable source citations.
---

# RAG and provenance-first retrieval

## Scope
RAG/pgvector are **not implemented in the reviewed repository**. Build PDF-first; web/arXiv later. Keep source attribution independent from LLM text generation.

## Procedure
1. Define `Source`, `SourceChunk`, provenance fields (owner/course/source, page, span/section, extraction version, hash) and a migration.
2. Secure ingestion: size/type limits, malware-aware sandboxing, file parsing timeout, archive/PDF bomb mitigation; URL ingestion with SSRF denial (redirect/IP/DNS/private network checks).
3. Begin with text PDFs, deterministic extraction and chunking plus page/offset mapping. Don't add OCR/CNN unless scans need it.
4. Start with PostgreSQL FTS + pgvector semantic retrieval. Benchmark lexical-only and vector-only baseline before adding hybrid fusion (RRF) or reranking.
5. Restrict retrieval at query time by authenticated owner and permitted course/source.
6. Construct cited answers only from retrieved authorized chunks; backend verifies every cited source ID/chunk/page against stored provenance. No retrieved evidence => say insufficient evidence.
7. Evaluate with curated owned documents: recall@k, citation precision, unsupported-claim rate, injection and cross-user leakage cases.

## Do not
No unverified source anchor, no user-supplied arbitrary page citations, no prompt instruction trust from PDF/web text. Don't claim RAG is PolySkill's verified backend algorithm.
