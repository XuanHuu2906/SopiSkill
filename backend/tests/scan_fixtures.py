"""Test helpers — sinh PDF "scan" (ảnh trang, KHÔNG có text layer).

Chỉ dùng cho test/eval P4.3: mô phỏng bản scan thật bằng cách render text ra ảnh
rồi nhúng ảnh vào PDF. `pypdf` trích text từ các trang này trả chuỗi rỗng, đúng
như PDF scan thật.

Không dùng trong production code. Cần Pillow (+ pypdf) nên test phải skip nếu
thiếu — xem `requirements-ocr.txt`.
"""

from __future__ import annotations

import io

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def scanned_pdf(
    pages: list[str], *, font_size: int = 34, dpi: int = 150, width: int = 1100
) -> bytes:
    """PDF gồm các trang ảnh (mỗi phần tử `pages` là text vẽ lên ảnh)."""
    from PIL import Image, ImageDraw

    images = []
    font = _font(font_size)
    for text in pages:
        lines = text.split("\n") or [""]
        height = max(200, 60 + 70 * len(lines))
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        y = 40
        for line in lines:
            draw.text((40, y), line, fill="black", font=font)
            y += 70
        images.append(image)

    buffer = io.BytesIO()
    images[0].save(
        buffer,
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=dpi,
    )
    return buffer.getvalue()


def merged_pdf(*parts: bytes) -> bytes:
    """Gộp nhiều PDF (ví dụ 1 trang text native + 1 trang scan) thành một file."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for part in parts:
        writer.append(PdfReader(io.BytesIO(part)))
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def ocr_dependencies_available() -> bool:
    """True khi có đủ engine + renderer + Pillow để chạy OCR thật."""
    import importlib.util

    for module in ("rapidocr", "pypdfium2", "PIL", "onnxruntime"):
        if importlib.util.find_spec(module) is None:
            return False
    return True
