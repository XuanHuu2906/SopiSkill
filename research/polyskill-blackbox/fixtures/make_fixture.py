"""Generate the synthetic 3-page PDF fixture used for the PolySkill black-box RAG probes.

The document is entirely fictional and contains no personal data. It exists only so
that we can ask "is the answer present in the uploaded source?" and compare against a
local oracle. Output: rag_synthetic_v1.pdf (3 pages).

Rendering path: local HTML -> Chrome headless --print-to-pdf.
Chrome is used read-only to render our own HTML; nothing is sent to PolySkill and no
network request leaves the machine.

Run:  python research/polyskill-blackbox/fixtures/make_fixture.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_PDF = HERE / "rag_synthetic_v1.pdf"
OUT_ORACLE = HERE / "oracle.local.json"

DISCLAIMER = "Tài liệu thử nghiệm hư cấu; không phải kiến thức thực tế."

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

PAGES: list[tuple[str, list[str]]] = [
    (
        "Trang 1 — Quy trình LUMORA-731",
        [
            "LUMORA-731 là một quy trình hư cấu gồm đúng ba giai đoạn, thực hiện theo thứ tự cố định:",
            "<ol><li><b>Giai đoạn 1: Chuẩn bị</b></li><li><b>Giai đoạn 2: Khớp mẫu</b></li><li><b>Giai đoạn 3: Xác thực</b></li></ol>",
            "Quy trình chỉ được coi là hoàn tất khi cả ba giai đoạn đã chạy xong.",
            "Không có giai đoạn thứ tư và không có giai đoạn nào được bỏ qua trong điều kiện thông thường.",
        ],
    ),
    (
        "Trang 2 — Chính sách ORBIT-294",
        [
            "ORBIT-294 là điểm kích hoạt dùng cho quy trình LUMORA-731.",
            "<b>Ngưỡng kích hoạt của ORBIT-294 là 17 đơn vị.</b>",
            "Khi số đơn vị đo được lớn hơn hoặc bằng 17, ORBIT-294 được coi là đã kích hoạt và quy trình LUMORA-731 được phép bắt đầu.",
            "Khi số đơn vị nhỏ hơn 17, ORBIT-294 không kích hoạt.",
        ],
    ),
    (
        "Trang 3 — Ngoại lệ MƯA TÍM và ORBIT-249",
        [
            "<b>Trong điều kiện MƯA TÍM</b>, quy trình LUMORA-731 bỏ qua giai đoạn Khớp mẫu và đi thẳng từ Chuẩn bị sang Xác thực.",
            "Điều kiện MƯA TÍM là ngoại lệ duy nhất được ghi nhận trong tài liệu này.",
            "ORBIT-249 là một điểm kích hoạt khác, hoàn toàn độc lập với ORBIT-294.",
            "<b>Ngưỡng kích hoạt của ORBIT-249 là 71 đơn vị.</b>",
            "Không được dùng ngưỡng của ORBIT-249 cho ORBIT-294 và ngược lại.",
        ],
    ),
]

HTML_HEAD = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>LUMORA-731 Synthetic Fixture (fictional)</title>
<style>
@page { size: A4; margin: 20mm 20mm 22mm 20mm; }
body { font-family: "Segoe UI","Arial",sans-serif; font-size: 14pt; line-height: 1.85; color:#111; }
h1 { font-size: 21pt; margin: 0 0 4mm 0; }
.note { font-style: italic; color:#7a2020; font-size: 11pt; margin: 0 0 9mm 0; }
.pg { page-break-after: always; }
.pg:last-of-type { page-break-after: auto; }
.foot { margin-top: 14mm; text-align:center; font-size:9pt; color:#555; }
ol { margin: 4mm 0 4mm 6mm; padding-left: 6mm; }
</style></head><body>
"""

EXPECTED = [
    {
        "test_id": "R1",
        "title": "Ba giai đoạn của LUMORA-731",
        "page": 1,
        "probes": [
            {
                "question": "Theo tài liệu, LUMORA-731 có những giai đoạn nào?",
                "must_include": ["Chuẩn bị", "Khớp mẫu", "Xác thực"],
                "must_not_include": ["giai đoạn thứ tư", "bốn giai đoạn"],
                "quote": "Giai đoạn 1: Chuẩn bị / Giai đoạn 2: Khớp mẫu / Giai đoạn 3: Xác thực",
            }
        ],
    },
    {
        "test_id": "R2",
        "title": "Diễn đạt tương đương (paraphrase)",
        "page": 1,
        "probes": [
            {
                "question": "Một quy trình gồm bước dọn dẹp đầu vào, so khớp với mẫu có sẵn rồi kiểm tra lại kết quả - tài liệu gọi đó là gì?",
                "must_include": ["LUMORA-731"],
                "must_not_include": [],
                "quote": "Chuẩn bị -> Khớp mẫu -> Xác thực; hỏi không lặp nhãn tiêu đề.",
            }
        ],
    },
    {
        "test_id": "R3",
        "title": "Phân biệt ORBIT-294 (17) và ORBIT-249 (71)",
        "page": None,
        "probes": [
            {
                "question": "ORBIT-294 ngưỡng bao nhiêu đơn vị?",
                "must_include": ["17"],
                "must_not_include": ["71"],
                "quote": "Ngưỡng kích hoạt của ORBIT-294 là 17 đơn vị.",
                "page": 2,
            },
            {
                "question": "ORBIT-249 ngưỡng bao nhiêu đơn vị?",
                "must_include": ["71"],
                "must_not_include": ["17"],
                "quote": "Ngưỡng kích hoạt của ORBIT-249 là 71 đơn vị.",
                "page": 3,
            },
        ],
    },
    {
        "test_id": "R4",
        "title": "Ngoại lệ MƯA TÍM kèm yêu cầu citation",
        "page": 3,
        "probes": [
            {
                "question": "MƯA TÍM là ngoại lệ gì? Dẫn nguồn cụ thể (trang/đoạn) nếu có.",
                "must_include": ["Khớp mẫu", "Xác thực"],
                "must_not_include": [],
                "quote": "Trong điều kiện MƯA TÍM, quy trình LUMORA-731 bỏ qua giai đoạn Khớp mẫu và đi thẳng từ Chuẩn bị sang Xác thực.",
            }
        ],
    },
    {
        "test_id": "R5",
        "title": "Câu hỏi không có đáp án trong nguồn (negative)",
        "page": None,
        "probes": [
            {
                "question": "Ai sáng chế LUMORA-731 vào năm nào?",
                "must_include": [],
                "must_not_include": ["<tên người cụ thể>", "<năm cụ thể>"],
                "expected_behavior": "Từ chối hoặc nói không đủ thông tin trong tài liệu.",
                "quote": "KHÔNG có trong tài liệu.",
            }
        ],
    },
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("chrome") or shutil.which("chrome.exe")
    if found:
        return found
    raise SystemExit("BLOCKED: chrome.exe not found; fixture cannot be rendered")


def build_html() -> str:
    parts = [HTML_HEAD]
    for index, (title, lines) in enumerate(PAGES, start=1):
        parts.append(f'<div class="pg"><h1>{title}</h1>')
        parts.append(f'<p class="note">{DISCLAIMER}</p>')
        for line in lines:
            parts.append(f"<p>{line}</p>" if not line.startswith("<ol") else line)
        parts.append(
            f'<div class="foot">LUMORA synthetic fixture — trang {index}/{len(PAGES)}</div>'
        )
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> None:
    chrome = find_chrome()
    html = build_html()
    work = Path(tempfile.mkdtemp(prefix="lumora-fixture-"))
    html_path = work / "fixture.html"
    pdf_path = work / "rag_synthetic_v1.pdf"
    html_path.write_text(html, encoding="utf-8")

    profile = work / "chrome-profile"
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not pdf_path.exists():
        raise SystemExit(f"BLOCKED: Chrome render failed rc={proc.returncode}\n{proc.stderr[-2000:]}")

    shutil.copyfile(pdf_path, OUT_PDF)
    raw = OUT_PDF.read_bytes()

    oracle = {
        "fixture": OUT_PDF.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "pages": len(PAGES),
        "disclaimer": DISCLAIMER,
        "generator": "matplotlib-free; Chrome headless print-to-pdf",
        "unique_facts": {
            "LUMORA-731.stages": ["Chuẩn bị", "Khớp mẫu", "Xác thực"],
            "ORBIT-294.threshold": 17,
            "ORBIT-249.threshold": 71,
            "MƯA TÍM.exception": "bỏ qua Khớp mẫu, đi thẳng Chuẩn bị -> Xác thực",
        },
        "expected": EXPECTED,
        "shareable": False,
        "note": "Local oracle only. Do not publish; contains the answer key for the probes.",
    }
    OUT_ORACLE.write_text(json.dumps(oracle, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"chrome: {chrome}")
    print(f"wrote {OUT_PDF} ({len(raw)} bytes, sha256 {oracle['sha256'][:16]}...)")
    print(f"wrote {OUT_ORACLE}")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
