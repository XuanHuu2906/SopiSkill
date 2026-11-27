# SopiSkill Multimodal Knowledge & Rich Lesson Plan (Code, LaTeX Formulas, Interactive Diagrams & Grounded Figures)

> **Status:** Active implementation roadmap — Phases `M0` (P0) and `M1` (P1) executing now; Phases `M2` (P2) and `M3` (P3) staged next.
> **Hardware Constraint Verified:** Host runs `Intel Core i5-13500H` (16 threads, `15 GiB` RAM, **no discrete NVIDIA GPU**). Therefore every pipeline stage is designed **Source-First, PDF-Last, CPU-Native** — zero local GPU/ColPali bloat, zero `eval()` on frontend or backend.
> **Cross-Repo Scope:**
> - SopiSkill Platform: `/home/nguyenhuu/Hoc Tap/Reverse Engineer` (`frontend/`, `ai-engine/`, `core-api/`)
> - Open Book Harvester: `/home/nguyenhuu/Hoc Tap/Cào sách` (`src/book_harvester/`, `tests/`)

---

## 1. Architectural Strategy ("Source-First + Hybrid GenUI + Grounded Figure Registry")

| Content Type | Optimal Production Engine | Why This Beats Naive PDF Scraping / Raw Mermaid |
| --- | --- | --- |
| **1. Code & Terminal** | Structured `figure.kind = "code"` + fenced ```` ```lang ```` & inline `` `code` `` rendering in `MathText.tsx` with zero-dependency deterministic tokenizer + Copy button | Immediately activates all `10,868` clean code chunks already in PostgreSQL (`official_docs` + CS textbooks) with 0 runtime cost and 0 XSS risk. |
| **2. Formulas & Symbols** | **Tier 1 (Source-First, 100% fidelity, 0 GPU):** arXiv HTML5/MathML (`ar5iv` / `arxiv.org/html` + LaTeX `<annotation encoding="application/x-tex">`) for `curated_classics` + OpenStax official GitHub CNXML/MathML (`openstax/osbooks-*`) for STEM textbooks.<br>**Tier 2 (PDF-only fallback, Phase M3):** Selective CPU IBM Docling or cloud OCR API only on formula-dense PDF pages. | Avoids 2D formula destruction from flat PyMuPDF text extraction; feeds native `$...$` / `$$...$$` directly into SopiSkill's self-hosted KaTeX (`MathText.tsx`). |
| **3. Process Diagrams & Function Plots** | Deterministic Structured JSON GenUI (`FigureRenderer.tsx` + `figure_validator.py`): upgraded multi-line Vietnamese SVG diagrams (`edge.label`, word-wrap) + safe interactive `kind = "plot"` (zero-eval math AST parser, coordinate axes, hover inspector, parameter sliders). | Zero syntax crashes (unlike free-form Mermaid with Vietnamese punctuation), 100% deterministic graph validation, and interactive variable manipulation. |
| **4. Real Textbook Figures** | **Grounded Figure Asset Registry on MinIO (`deploy-minio-1`):** Extract original high-res figures from OpenStax `media/` & arXiv HTML/source (Phase M1) and Docling/PyMuPDF 200-DPI Figure-BBox crops for PDF-only books (Phase M3). Store `{figureId, url/minioKey, page, label, caption, altText}` linked to `section_anchor`. | Preserves vector diagrams (which `page.get_images()` misses), avoids 50x vector bloat from ColPali, and prevents LLM URL hallucination/SSRF via server-verified `sourceFigureId`. |

---

## 2. Phase Breakdown

### Phase M0 (P0) — Rich Code, Formula, Multi-line Diagram & Interactive Function Plot GenUI
**Goal:** Upgrade SopiSkill's frontend lesson renderer and `ai-engine` figure validator/prompts so lessons natively display highlighted code blocks, unwrapped Vietnamese SVG diagrams with edge labels, and interactive mathematical function plots safely (zero `eval()`, zero breaking API changes).

**Modules & Files:**
- `frontend/src/components/lesson/MathText.tsx`
  - Add fenced code block (` ```lang ... ``` `) and inline `` `code` `` parsing alongside `$$...$$`, `$...$`, and `{termKey}` chips.
  - Export reusable `CodeBlockCard` (deterministic keyword/string/comment/number tokenizer for Python, TypeScript/JS, Java, Rust, SQL, Bash, Go, C/C++; line numbers; language pill; accessible Copy button).
- `frontend/src/components/lesson/FigureRenderer.tsx`
  - Add multi-line word wrapping (`wrapSvgLabel`) for SVG diagram nodes (removes hard `.slice(0, 18)` / `.slice(0, 22)` truncation on Vietnamese labels) and render `edge.label` badges on `flow` / `branch` / `hub` connectors.
  - Add `kind: "code"` (`code`, `language`, `highlightLines`, `title`, `caption`).
  - Add `kind: "plot"` (`functions: [{expr, label, color}]`, `xRange`, `yRange`, `points`, `params: [{name, label, min, max, step, value}]`):
    - Pure TypeScript recursive-descent safe mathematical expression evaluator (whitelist: `+ - * / ^`, `x`, declared parameter names, `sin cos tan asin acos atan exp ln log sqrt abs floor ceil pi e` — **zero `eval` / `Function()`**).
    - Interactive SVG coordinate plane with grid, axes, legend, hover crosshair readout `(x, f(x))`, and live range sliders when `params` are present.
- `ai-engine/app/agents/figure_validator.py`
  - Extend `ALLOWED_FIGURE_KINDS` to `{"formula", "table", "visual", "diagram", "code", "plot"}`.
  - Validate `code` (`code` non-empty `<= 4000` chars, optional safe `language`, optional `highlightLines` within line bounds).
  - Validate `plot` (`xRange`/`yRange` ordered finite tuples, `1..4` functions, strict Python `ast`-based safe expression validator rejecting imports/attributes/calls outside math whitelist, `params` bounds check).
- `ai-engine/app/agents/providers.py`
  - Document `code` and `plot` figure kinds in the Lesson Generator system prompt (preserving existing `MockProvider` deterministic behavior).
- `ai-engine/tests/test_phase4_rich_lesson.py`
  - Add unit tests for valid/invalid `code` and `plot` figures (including AST injection attempts like `__import__('os')` or `eval()` rejected deterministically).

**Acceptance Criteria:**
- `frontend`: `npm run typecheck`, `npm run lint`, and `npm run build` pass with `0` errors and `0` warnings.
- `ai-engine`: `pytest` (all non-destructive tests + `test_phase4_rich_lesson.py`) passes 100%, `bandit -r app scripts -q` reports `0` issues.
- Backward-compatible: all existing `formula`, `table`, `visual`, `diagram` lessons render identically or cleaner without truncating Vietnamese labels.

---

### Phase M1 (P1) — Source-First LaTeX & Original Figures Extractor (arXiv HTML5/ar5iv + OpenStax CNXML/Media)
**Goal:** Replace degraded flat-PDF text in high-value math/ML/STEM sources with **100% lossless LaTeX (`$...$` / `$$...$$`) and extracted original figures (`figures_manifest.json`)** using zero-GPU source-first extractors, and immediately sync enriched LaTeX chunks into live PostgreSQL.

**Modules & Files (`/home/nguyenhuu/Hoc Tap/Cào sách`):**
- `src/book_harvester/rich_sources.py`
  - **1. arXiv HTML5 / ar5iv Extractor (`extract_arxiv_html_to_clean_markdown`):**
    - Fetches official `https://arxiv.org/html/{arxiv_id}` (fallback `https://ar5iv.labs.arxiv.org/html/{arxiv_id}`) through `SafeHttpClient` (strict HTTPS allowlist + SSRF protection).
    - Extracts `<annotation encoding="application/x-tex">` directly from every `<math>` node (inline `$ ... $` and display `$$ ... $$` equations), preserving 100% author-written LaTeX!
    - Preserves structured `<table>` as clean Markdown tables and `<section>` headings as clean `##` / `###` hierarchy; drops `References` / `Bibliography` / `Acknowledgments`.
    - Extracts `<figure>` assets (`figure_id`, `label`, `caption`, `alt`, original image URL + optional local download to `figures/` folder as WebP/PNG) into `figures_manifest.json`.
  - **2. OpenStax CNXML / MathML Extractor (`extract_openstax_cnxml_to_clean_markdown`):**
    - Parses official OpenStax GitHub repositories (`github.com/openstax/osbooks-*` shallow clone or tarball): `collections/*.collection.xml` → ordered `modules/m*/index.cnxml` + `media/` original images.
    - Deterministic **MathML → LaTeX converter** (`mathml_to_latex`) handling `<mfrac>`, `<msup>`, `<msub>`, `<msubsup>`, `<msqrt>`, `<mroot>`, `<mtable>`, `<mover>`, `<munder>`, `<mfenced>`, `<mi>`, `<mn>`, `<mo>`, `<mtext>`, Greek symbols, and display equations (`<equation>` → `$$...$$`).
    - Copies/indexes original `<figure>` media files (`media/...`) + official instructor-authored `alt` text + captions into `figures/` and `figures_manifest.json`.
    - Skips `Review Questions`, `Exercises`, `Answer Key`, `Index`, `Preface` deterministically.
- `src/book_harvester/cli.py`
  - Add CLI command `book-harvester enrich-rich` (`--arxiv-classics`, `--openstax-slugs`, `--download-figures`) to run Source-First enrichment cleanly and update `catalog.db` + `clean.md` + `chunks.jsonl` + `brief.json` + `figures_manifest.json`.
- `tests/test_rich_sources.py`
  - Offline unit tests covering:
    - arXiv/ar5iv HTML5 with `<math><annotation encoding="application/x-tex">` (inline + display) + `<figure>` extraction + references pruning.
    - OpenStax CNXML with MathML (`mfrac`, `msqrt`, `msubsup`, `mtable`) → exact LaTeX `$...$` / `$$...$$` + `<figure>` media/alt-text extraction.
    - Chunking integrity verifying `$$...$$` display equations stay atomic (`chunks.jsonl` has balanced `$$`).

**Acceptance Criteria:**
- `cd "/home/nguyenhuu/Hoc Tap/Cào sách" && uv run pytest -v` — 100% passing (all existing 27 tests + new `test_rich_sources.py`).
- Live enrichment executed on `curated_classics` (arXiv papers with official HTML available) + core OpenStax STEM repositories (e.g., *Calculus Volume 1*, *University Physics Volume 1*, *Introductory Statistics 2e*, *Chemistry 2e*).
- Re-sync enriched sources into live PostgreSQL (`rag.document_chunks`) and prove via SQL that `chunks_with_latex_blocks` jumps from `54` to **`> 1,000` verified LaTeX chunks** and `figures_manifest.json` contains real extracted figures + captions.

---

### Phase M2 (P2) — Grounded Figure Registry in MinIO + RAG `read_source` + Lesson `sourceFigureId` *(Planned Next)*
**Goal:** Wire extracted book figures end-to-end from MinIO object storage through Hybrid RAG retrieval into verified lesson `block.image` rendering and the local Chunks Explorer UI.

**Modules & Files:**
- **Alembic Migration (`ai-engine/alembic/versions/0003_chunk_figures_metadata.py`):**
  - Add `metadata JSONB NOT NULL DEFAULT '{}'::jsonb` to `rag.document_chunks` (storing `{"figures": [{"figureId", "minioKey", "label", "caption", "alt", "page"}]}`) OR dedicated `rag.source_figures` table indexed by `(owner_id, source_id, section_anchor)`.
- **MinIO Uploader (`ai-engine/scripts/import_open_library.py`):**
  - Read `figures_manifest.json` during library import; normalize images to `<= 1200px` WebP (`quality=82`); upload to MinIO bucket `sopiskill-sources` under `library-figures/{external_key}/{figure_id}.webp` (idempotent by SHA-256).
- **Safe Media Proxy Endpoint (`core-api`):**
  - Add `GET /v1/library/figures/{sourceId}/{figureId}` validating public visibility or tenant course ownership before streaming bytes/presigned redirect from MinIO (strict Content-Type allowlist `image/webp`, `image/png`, `image/jpeg`, `Cache-Control: public, max-age=86400`, zero direct unauthenticated bucket exposure).
- **RAG & Lesson Generator Grounding (`ai-engine/app/rag/repository.py`, `lesson_generator.py`, `figure_validator.py`):**
  - Return `availableFigures` in `read_source` tool output.
  - Allow `teach.sourceFigureId` in `save_lesson`; server deterministically resolves `sourceFigureId` → verified `block.image = {url, alt, caption}` (rejects unknown IDs, enforces mutual exclusion with `block.figure`).
- **Chunks Explorer UI:** Render thumbnail + zoomable lightbox of linked figures right inside each chunk card.

**Acceptance Criteria:**
- End-to-end integration test: importing a book with `figures_manifest.json` uploads WebP to MinIO, `read_source` surfaces `availableFigures`, `save_lesson` binds verified `sourceFigureId`, and `GET /v1/library/figures/...` returns `200 image/webp` while unauthorized/missing IDs return `404`/`403`.

---

### Phase M3 (P3) — Selective CPU Docling & Figure Bounding-Box 200-DPI Crop for PDF-Only Books *(Planned Final)*
**Goal:** Cover remaining high-value PDF-only textbooks (`OTL`, `DOAB`, `archive`) that have no GitHub/LaTeX upstream source without requiring a GPU.

**Modules & Files (`/home/nguyenhuu/Hoc Tap/Cào sách`):**
- **Selective Page Router (`src/book_harvester/pdf_rich_router.py`):**
  - Fast PyMuPDF pre-scan detects only pages with heavy math/vector diagrams (`formula_page_score` or `Figure X.Y` caption + vector drawing density).
  - Runs **IBM Docling (MIT, CPU-friendly)** or optional **Cloud OCR API** (`MISTRAL_OCR_API_KEY` / Gemini Flash when configured) strictly on flagged STEM pages (avoiding full-book OCR overhead).
- **Figure Bounding-Box Rasterizer:**
  - Uses layout `Figure` bounding boxes + `page.get_pixmap(clip=bbox, dpi=200)` → WebP so vector schematics, chemical structures, and circuit diagrams are captured cleanly with captions.
- **VLM Alt-Text Enrichment (Optional Offline Batch):**
  - Generates concise accessible `alt` descriptions for figures that lack captions, stored in `figures_manifest.json`.

**Acceptance Criteria:**
- Benchmark report on 5 PDF-only STEM OTL books measuring formula LaTeX recovery rate, vector-figure recall (vs naive `page.get_images()`), CPU runtime, and RAM peak `< 4 GB`.

---

## 3. Explicit Exclusions & Safety Invariants
- **NO `eval()`, `new Function()`, or raw Mermaid/HTML injection** for plots or code blocks — strict AST/recursive-descent math parser and React JSX tokenization only.
- **NO destructive DB drops** (`docker compose down -v`, `alembic downgrade base` on live DB, or unbacked `DELETE`).
- **NO external URLs trusted from LLM output** — figures must resolve exclusively through server-owned `sourceFigureId` / MinIO proxy.
- **NO local GPU assumptions** — all P0/P1/P2/P3 paths run reliably on CPU (`i5-13500H`, `15 GiB` RAM).
