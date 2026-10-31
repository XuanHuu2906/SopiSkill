"""Test helpers — sinh PDF tối giản (không cần thư viện ngoài để tạo fixture).

Chỉ dùng cho test: tạo PDF text có nhiều trang + heading để kiểm tra extraction/
chunking/provenance. Không dùng trong production code.
"""

from __future__ import annotations

import io


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(pages: list[str], *, font_size: int = 11) -> bytes:
    """Trả bytes PDF với mỗi phần tử `pages` là text của một trang."""
    n = len(pages)
    font_no = 3
    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n))
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>"
    for i, text in enumerate(pages):
        content_no = 4 + 2 * i
        page_no = 5 + 2 * i
        body = ["BT", f"/F1 {font_size} Tf", "14 TL", "56 780 Td"]
        for line in text.split("\n"):
            body.append(f"({_escape(line)}) Tj T*")
        body.append("ET")
        stream = "\n".join(body)
        objects[content_no] = (
            f"<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream"
        )
        objects[page_no] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_no} 0 R >> >> /Contents {content_no} 0 R >>"
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for no in sorted(objects):
        offsets[no] = out.tell()
        out.write(f"{no} 0 obj\n{objects[no]}\nendobj\n".encode())
    xref = out.tell()
    total = max(objects) + 1
    out.write(f"xref\n0 {total}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for no in range(1, total):
        out.write(f"{offsets[no]:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


# Font chuẩn (Helvetica/Type1) không có ToUnicode CMap ⇒ PDF fixture dùng text
# ASCII để pypdf trích đúng byte. Text tiếng Việt được kiểm ở tầng chunk (không
# phụ thuộc font PDF) trong test riêng.
_LONG_PARAGRAPH = " ".join(
    ["Python is a high level language that is readable and has a large ecosystem."] * 12
)


def pdf_with_heading_pages() -> bytes:
    """3 trang: mỗi trang có heading + đoạn text đủ dài để chunk."""
    return make_pdf(
        [
            f"Chapter 1: Introduction\n{_LONG_PARAGRAPH}",
            f"Chapter 2: Variables and data types\n{_LONG_PARAGRAPH}",
            f"Chapter 3: Functions\n{_LONG_PARAGRAPH}",
        ]
    )


def blank_pdf(page_count: int = 2) -> bytes:
    """PDF chỉ có trang trắng (mô phỏng bản scan không có text layer)."""
    return make_pdf([""] * page_count)
