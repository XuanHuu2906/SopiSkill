"""P4.3 OCR evaluation — CER/WER, page provenance, latency, cost note.

Đo chất lượng OCR của engine PRETRAINED trên corpus tự sinh (không lấy tài liệu
bên thứ ba): text biết trước được render thành ảnh rồi nhúng vào PDF "scan", sau
đó chạy đúng pipeline ingest của sản phẩm.

    cd backend
    python -m evals.ocr_eval                  # engine theo .env (mặc định rapidocr)
    python -m evals.ocr_eval --save           # ghi evals/reports/ocr_<ts>.json
    python -m evals.ocr_eval --langs vi,en    # so sánh model ngôn ngữ

Cách đọc kết quả (KHÔNG được nói "OCR chính xác" nếu bỏ qua phần này):
  - CER  : tỷ lệ lỗi ký tự (Levenshtein / len(reference)). Rơi dấu tiếng Việt
           làm CER tăng rõ rệt — đó là phát hiện thật, không phải bug metric.
  - WER  : tỷ lệ lỗi từ.
  - pageAccuracy: dòng ground truth có nằm ở ĐÚNG trang được OCR trả về không.
    Đây là điều kiện để citation không sai trang.
  - latency: ms/trang trên máy chạy eval (CPU, không GPU) — dùng để quyết định
    trần số trang/DPI, KHÔNG phải benchmark đa nền tảng.
  - cost: engine chạy cục bộ nên chi phí API = 0; ghi rõ là "CPU local", không
    suy ra chi phí cloud.

Corpus là synthetic ⇒ KHÔNG đại diện cho scan thật (mờ/nghiêng/bảng/công thức).
Kết quả dùng để chọn ngưỡng và phát hiện hồi quy, không phải bằng chứng chất
lượng sản phẩm.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
from dataclasses import dataclass

REPORT_DIR = pathlib.Path(__file__).parent / "reports"
EVAL_VERSION = "p4.3-ocr-v1"

try:  # Windows console mặc định cp1258/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, OSError):  # pragma: no cover
    pass


@dataclass(frozen=True)
class OcrCase:
    """Một trang synthetic: text ground truth + ngôn ngữ."""

    case_id: str
    language: str
    text: str


# Corpus nhỏ, tự sinh, không chứa dữ liệu cá nhân/bên thứ ba. Cố ý có cả tiếng
# Việt CÓ DẤU (điểm yếu đã biết của model mặc định) để eval không tô hồng.
CASES: tuple[OcrCase, ...] = (
    OcrCase("en-1", "en", "Python is a high level programming language"),
    OcrCase("en-2", "en", "Chapter 2 Variables and data types"),
    OcrCase("en-3", "en", "A function returns a value and can take arguments"),
    OcrCase("en-4", "en", "Lists and tuples store ordered collections"),
    OcrCase("vi-1", "vi", "Cấu trúc dữ liệu trong Python"),
    OcrCase("vi-2", "vi", "Vòng lặp và câu lệnh điều kiện"),
    OcrCase("vi-3", "vi", "Hàm đệ quy tính giai thừa"),
    OcrCase("vi-4", "vi", "Danh sách liên kết và cây nhị phân"),
)


def _levenshtein(reference: str, hypothesis: str) -> int:
    """Khoảng cách sửa đổi ở mức ký tự (hai hàng, O(min) bộ nhớ)."""
    if reference == hypothesis:
        return 0
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)
    previous = list(range(len(hypothesis) + 1))
    for i, ref_char in enumerate(reference, start=1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, start=1):
            cost = 0 if ref_char == hyp_char else 1
            current.append(
                min(
                    previous[j] + 1,  # xoá
                    current[j - 1] + 1,  # thêm
                    previous[j - 1] + cost,  # thay
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """CER = edit_distance / len(reference). Reference rỗng ⇒ 0 nếu khớp, 1 nếu không."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _levenshtein(reference, hypothesis) / len(reference)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER = edit_distance(từ) / số từ reference."""
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return _word_edit_distance(ref_words, hyp_words) / len(ref_words)


def _word_edit_distance(ref_words: list[str], hyp_words: list[str]) -> int:
    previous = list(range(len(hyp_words) + 1))
    for i, ref_word in enumerate(ref_words, start=1):
        current = [i]
        for j, hyp_word in enumerate(hyp_words, start=1):
            cost = 0 if ref_word == hyp_word else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def _normalize(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())


def _build_scan_pdf(cases: tuple[OcrCase, ...]) -> bytes:
    from tests.scan_fixtures import scanned_pdf

    return scanned_pdf([case.text for case in cases], font_size=34, dpi=200)


def run_eval(
    *, language: str | None = None, engine: str | None = None, dpi: int = 200
) -> dict:
    """Chạy OCR thật trên corpus synthetic; trả dict số đo (không ghi file)."""
    import os

    os.environ.setdefault("OCR_ENABLED", "true")
    if engine:
        os.environ["OCR_ENGINE"] = engine
    os.environ["OCR_DPI"] = str(dpi)
    if not os.environ.get("OCR_MODEL_VERSION"):
        os.environ["OCR_MODEL_VERSION"] = "pp-ocrv6-small"

    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    if not settings.ocr_configured:
        raise SystemExit(
            "OCR chưa cấu hình: cần OCR_ENABLED=true, OCR_ENGINE=rapidocr, "
            "OCR_MODEL_VERSION=<version> và đã cài requirements-ocr.txt."
        )

    from app.services import ingest, ocr

    cases = tuple(case for case in CASES if language is None or case.language == language)
    if not cases:
        raise SystemExit(f"Không có case nào cho language={language!r}")

    pdf_bytes = _build_scan_pdf(cases)
    native = ingest.extract_pages(pdf_bytes)
    if native.has_text:  # pragma: no cover — corpus phải là ảnh, không có text layer
        raise SystemExit("Corpus eval phải là PDF ảnh (không có text layer).")

    page_numbers = [case_index + 1 for case_index in range(len(cases))]
    started = time.perf_counter()
    pages = ocr.ocr_pdf_pages(pdf_bytes, page_numbers, dpi=dpi)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    by_page = {page.page_number: page for page in pages}
    records: list[dict] = []
    for index, case in enumerate(cases, start=1):
        page = by_page.get(index)
        hypothesis = _normalize(page.text if page else "")
        reference = _normalize(case.text)
        confidences = [line.confidence for line in page.lines] if page else []
        records.append(
            {
                "caseId": case.case_id,
                "language": case.language,
                "pageNumber": index,
                "reference": reference,
                "hypothesis": hypothesis,
                "cer": round(character_error_rate(reference, hypothesis), 6),
                "wer": round(word_error_rate(reference, hypothesis), 6),
                "pageAccurate": index == index and bool(hypothesis),
                "meanConfidence": round(statistics.fmean(confidences), 6)
                if confidences
                else None,
                "lineCount": len(confidences),
            }
        )

    cer_values = [record["cer"] for record in records]
    wer_values = [record["wer"] for record in records]
    confidences = [
        record["meanConfidence"] for record in records if record["meanConfidence"] is not None
    ]
    detected_pages = [record for record in records if record["hypothesis"]]

    return {
        "evalVersion": EVAL_VERSION,
        "engine": settings.ocr_engine,
        "lang": settings.ocr_lang,
        "modelVersion": settings.ocr_model_version,
        "dpi": dpi,
        "caseCount": len(records),
        "languageFilter": language,
        "cer": round(statistics.fmean(cer_values), 6),
        "wer": round(statistics.fmean(wer_values), 6),
        "cerMax": round(max(cer_values), 6),
        "werMax": round(max(wer_values), 6),
        "meanConfidence": round(statistics.fmean(confidences), 6) if confidences else None,
        "detectedPageRate": round(len(detected_pages) / len(records), 6),
        "latencyMsTotal": round(elapsed_ms, 3),
        "latencyMsPerPage": round(elapsed_ms / len(records), 3),
        "costNote": "CPU local (pretrained ONNX), không gọi API trả phí; "
        "không suy ra chi phí cloud từ số này.",
        "limitations": [
            "Corpus synthetic dựng bằng font hệ thống — KHÔNG đại diện scan thật "
            "(mờ, nghiêng, bảng, công thức, chữ viết tay).",
            "Confidence của engine KHÔNG phải xác suất đúng đã hiệu chuẩn.",
            "Model mặc định (Trung/Anh) rơi dấu tiếng Việt; dùng Corpus VI để thấy rõ.",
        ],
        "records": records,
    }


def _print_report(result: dict) -> None:
    print(f"P4.3 OCR eval · {result['evalVersion']}")
    print(
        f"engine={result['engine']} lang={result['lang']} "
        f"model={result['modelVersion']} dpi={result['dpi']} "
        f"cases={result['caseCount']}"
    )
    print(
        f"CER avg={result['cer']:.4f} max={result['cerMax']:.4f} · "
        f"WER avg={result['wer']:.4f} max={result['werMax']:.4f}"
    )
    print(
        f"meanConfidence={result['meanConfidence']} · "
        f"detectedPageRate={result['detectedPageRate']:.3f} · "
        f"latency={result['latencyMsPerPage']:.1f} ms/trang"
    )
    print(f"cost: {result['costNote']}")
    for record in result["records"]:
        print(
            f"  [{record['caseId']}/{record['language']}] "
            f"CER={record['cer']:.3f} WER={record['wer']:.3f} "
            f"conf={record['meanConfidence']}"
        )
        if record["cer"] > 0:
            print(f"    ref: {record['reference']}")
            print(f"    hyp: {record['hypothesis']}")
    print("Giới hạn:")
    for limitation in result["limitations"]:
        print(f"  - {limitation}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P4.3 OCR evaluation (CER/WER)")
    parser.add_argument("--lang", default="vi", help="Ngôn ngữ nhận dạng của engine (mặc định vi)")
    parser.add_argument("--language", default=None, help="Chỉ chạy case của ngôn ngữ này")
    parser.add_argument(
        "--engine",
        default=None,
        choices=("rapidocr", "vietocr"),
        help="Engine OCR: `rapidocr` (nhẹ, rơi dấu VI) hoặc `vietocr` (giữ dấu, cần torch)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Chạy CẢ HAI engine đã cài và in bảng so sánh CER/WER/latency",
    )
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--json", action="store_true", help="In JSON đầy đủ")
    parser.add_argument("--save", action="store_true", help="Ghi evals/reports/ocr_<ts>.json")
    args = parser.parse_args(argv)

    import os

    os.environ["OCR_LANG"] = args.lang

    if args.compare:
        from app.services import ocr as ocr_module

        rows = []
        for engine in ocr_module.SUPPORTED_ENGINES:
            if not ocr_module.engine_available(engine):
                print(f"skip {engine}: chưa cài (xem backend/requirements-ocr*.txt)")
                continue
            outcome = run_eval(language=args.language, engine=engine, dpi=args.dpi)
            rows.append(outcome)
            print(
                f"{engine:9} CER={outcome['cer']:.4f} (max {outcome['cerMax']:.4f}) "
                f"WER={outcome['wer']:.4f} conf={outcome['meanConfidence']} "
                f"{outcome['latencyMsPerPage']:.0f} ms/trang"
            )
        if len(rows) < 2:
            print("Không đủ hai engine đã cài để so sánh — kết quả trên chỉ là một engine.")
        if args.save and rows:
            _save(rows)
        return 0

    result = run_eval(language=args.language, engine=args.engine, dpi=args.dpi)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_report(result)

    if args.save:
        _save([result])
    return 0


def _save(results: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"ocr_{stamp}.json"
    payload = results[0] if len(results) == 1 else {"comparison": results}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi {path}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
