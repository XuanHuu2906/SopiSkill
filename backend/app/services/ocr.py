"""OCR adapter cho PDF scan (P4.3) — engine pretrained, KHÔNG train lại.

Nguyên tắc:
  - **Pretrained only**: hai engine, chọn bằng `OCR_ENGINE`:
      - `rapidocr` (mặc định): ONNX PP-OCR (CNN det + CNN rec), nhẹ, chạy cục bộ.
        Charset KHÔNG có nguyên âm tiếng Việt có dấu thanh ⇒ CER VI ≈ 9%
        (đo trong `evals/ocr_eval.py`), đã kiểm chứng charset của file ONNX.
      - `vietocr`: recognizer Transformer (VGG-Transformer) pretrained tiếng Việt
        + detector của rapidocr. Đo trên cùng corpus: CER VI 0.0086 / WER 0.0417
        so với 0.0939 / 0.4137 của rapidocr. Đổi lại cần `torch` (~250MB) và
        ~4.4 s/trang so với ~3.1 s/trang (CPU).
    Không fine-tune, không tải model từ mạng trong lúc ingest — model phải có sẵn
    trong môi trường (image/venv).
  - **Fail-fast**: bật OCR mà engine không cài/không load được ⇒
    `OCR_NOT_CONFIGURED`, KHÔNG âm thầm quay về "no_text".
  - **Không tin file**: render qua `pypdfium2` trong process, chỉ đọc bytes; không
    shell, không network, trần thời gian/số trang/DPI.
  - **Provenance thật**: mỗi dòng OCR giữ `bbox` chuẩn hoá theo trang [0,1] và
    `confidence`. Caller tự cắt bbox theo khoảng ký tự của chunk.
  - **Trung thực chất lượng**: confidence của engine KHÔNG phải xác suất đúng đã
    hiệu chuẩn; chất lượng phải đo bằng CER/WER trên corpus thật
    (`evals/ocr_eval.py`).

Giới hạn đã biết (ghi trong docs/specs/21-P43-OCR.md):
  - Model mặc định train trên tiếng Trung/Anh; tiếng Việt có dấu bị rơi dấu.
  - Bảng/công thức không được dựng lại theo cấu trúc, chỉ là dòng text.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass, field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Thứ tự = ưu tiên gợi ý; mỗi engine có bộ phụ thuộc khác nhau (xem
# requirements-ocr.txt và requirements-ocr-vietocr.txt).
SUPPORTED_ENGINES = ("rapidocr", "vietocr")
_VIETOCR_MODEL_NAME = "vgg_transformer"
_VIETOCR_REQUIRED = ("vietocr", "torch", "PIL")
_RAPIDOCR_REQUIRED = ("rapidocr", "onnxruntime", "numpy")


class OcrError(Exception):
    """Lỗi OCR có mã ổn định + thông điệp an toàn (không chứa nội dung tài liệu)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_error(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class OcrLine:
    """Một dòng text OCR: nội dung + confidence + bbox chuẩn hoá `(x0,y0,x1,y1)`."""

    text: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass
class OcrPage:
    page_number: int
    lines: list[OcrLine] = field(default_factory=list)
    width: int = 0
    height: int = 0

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text.strip())


_ENGINE: object | None = None
_ENGINE_KEY: tuple[str, str] | None = None
_ENGINE_LOCK = threading.Lock()
# Detector dùng chung cho engine chỉ-có-recognizer (VietOCR).
_DETECTOR: object | None = None
_DETECTOR_KEY: str | None = None


def _engine_key(engine: str, lang: str) -> tuple[str, str]:
    return (engine.strip().lower(), (lang or "").strip().lower())


def _module_available(name: str) -> bool:
    """Indirection để test giả lập thiếu phụ thuộc mà không gỡ package thật."""
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover — spec hỏng cũng coi là thiếu
        return False


def engine_available(engine: str | None = None) -> bool:
    """True khi engine được cấu hình thực sự importable (không tải model)."""
    name = (engine or get_settings().ocr_engine or "").strip().lower()
    if name not in SUPPORTED_ENGINES:
        return False

    # Renderer dùng chung cho mọi engine.
    for module in ("pypdfium2", "PIL"):
        if not _module_available(module):
            return False

    if name == "vietocr":
        return all(_module_available(module) for module in _VIETOCR_REQUIRED)
    return all(_module_available(module) for module in _RAPIDOCR_REQUIRED)


def configured(settings=None) -> bool:
    """OCR có hiệu lực? = bật cờ AND engine hợp lệ AND phiên bản model khai báo."""
    settings = settings or get_settings()
    if not settings.ocr_enabled:
        return False
    if not (settings.ocr_model_version or "").strip():
        return False
    return engine_available(settings.ocr_engine)


def _get_engine(engine: str, lang: str):
    """Engine dùng lại giữa các lần gọi (nạp model ~1–2s); có lock vì ONNX/PyTorch
    không hứa thread-safe cho cùng session."""
    global _ENGINE, _ENGINE_KEY

    key = _engine_key(engine, lang)
    with _ENGINE_LOCK:
        if _ENGINE is not None and _ENGINE_KEY == key:
            return _ENGINE
        try:
            if key[0] == "vietocr":
                _ENGINE = _load_vietocr()
            else:
                from rapidocr import RapidOCR

                params = {"Rec.lang_type": key[1]} if key[1] else None
                _ENGINE = RapidOCR(params=params) if params else RapidOCR()
        except OcrError:
            raise
        except Exception as exc:  # noqa: BLE001 — lỗi model phải thành mã ổn định
            raise OcrError(
                "OCR_NOT_CONFIGURED",
                f"Không khởi tạo được engine OCR «{engine}»: {type(exc).__name__}.",
            ) from exc
        _ENGINE_KEY = key
        logger.info("ocr engine ready engine=%s lang=%s", key[0], key[1] or "default")
        return _ENGINE


def _load_vietocr():
    """Nạp VietOCR (Predictor) — model pretrained tiếng Việt, device CPU.

    Weight phải có sẵn trong cache/`OCR_VIETOCR_WEIGHTS`; KHÔNG để ingest tự tải
    từ mạng (ingest phải chạy được offline).
    """
    settings = get_settings()
    from vietocr.tool.config import Cfg
    from vietocr.tool.predictor import Predictor

    config = Cfg.load_config_from_name(_VIETOCR_MODEL_NAME)
    config["device"] = "cpu"
    if settings.ocr_vietocr_weights:
        config["weights"] = settings.ocr_vietocr_weights
    if settings.ocr_vietocr_config:
        from vietocr.tool.config import Cfg as _Cfg

        config = _Cfg.load_config_from_file(settings.ocr_vietocr_config)
        config["device"] = "cpu"
    return Predictor(config)


def _detect_boxes(image) -> tuple[list, int, int]:
    """Detector dùng chung: lấy box dòng chữ từ rapidocr (chỉ det, không rec).

    VietOCR là recognizer thuần; cần detector để biết cắt dòng ở đâu. Dùng lại
    detector của rapidocr để không thêm model thứ ba.
    """
    import numpy as np
    from rapidocr import RapidOCR

    global _DETECTOR, _DETECTOR_KEY
    with _ENGINE_LOCK:
        if _DETECTOR is None:
            _DETECTOR = RapidOCR()
        detector = _DETECTOR
    array = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()  # RGB → BGR
    raw = detector(array, use_det=True, use_cls=False, use_rec=False)
    # `boxes` là numpy array ⇒ không được dùng `or []` (truth-value ambiguous).
    detected = getattr(raw, "boxes", None)
    boxes = [] if detected is None else list(detected)
    width, height = image.size
    return boxes, width, height


def _recognize_vietocr(engine, image, boxes) -> tuple[list[str], list[float]]:
    """Chạy VietOCR cho từng box (crop theo bbox) và trả text + probability."""
    texts: list[str] = []
    scores: list[float] = []
    for box in boxes:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        left, right = max(0, int(min(xs))), min(image.width, int(max(xs)))
        top, bottom = max(0, int(min(ys))), min(image.height, int(max(ys)))
        if right <= left or bottom <= top:
            texts.append("")
            scores.append(0.0)
            continue
        crop = image.crop((left, top, right, bottom))
        try:
            text, probability = engine.predict(crop, return_prob=True)
        except Exception:  # noqa: BLE001 — một dòng lỗi không làm hỏng cả trang
            texts.append("")
            scores.append(0.0)
            continue
        texts.append(text or "")
        scores.append(float(probability))
    return texts, scores


def reset_engine() -> None:
    """Bỏ cache engine/detector (test đổi cấu hình / giải phóng bộ nhớ)."""
    global _ENGINE, _ENGINE_KEY, _DETECTOR, _DETECTOR_KEY
    with _ENGINE_LOCK:
        _ENGINE = None
        _ENGINE_KEY = None
        _DETECTOR = None
        _DETECTOR_KEY = None


def _render_page(data: bytes, page_number: int, dpi: int):
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(io.BytesIO(data))
    try:
        if page_number < 1 or page_number > len(document):
            raise OcrError("OCR_FAILED", "Trang yêu cầu nằm ngoài phạm vi tài liệu.")
        page = document[page_number - 1]
        bitmap = page.render(scale=dpi / 72.0)
        image = bitmap.to_pil()
        return image
    finally:
        document.close()


def _normalize_bbox(points, width: int, height: int) -> tuple[float, float, float, float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    x0 = min(xs) / width if width else 0.0
    x1 = max(xs) / width if width else 1.0
    y0 = min(ys) / height if height else 0.0
    y1 = max(ys) / height if height else 1.0
    clamp = lambda value: min(1.0, max(0.0, value))  # noqa: E731
    return (clamp(x0), clamp(y0), clamp(x1), clamp(y1))


def _as_sequence(value):
    """Chuẩn hoá list/tuple/numpy array về list (tránh `or []` trên ndarray)."""
    if value is None:
        return []
    return list(value)


def build_lines(
    boxes,
    texts,
    scores,
    *,
    width: int,
    height: int,
    min_confidence: float,
) -> list[OcrLine]:
    """Ghép det-box + rec-text thành `OcrLine` (hàm thuần, test được offline).

    Bỏ dòng rỗng và dòng dưới `min_confidence` — KHÔNG hạ ngưỡng để lấy thêm chữ.
    Box thiếu ⇒ bbox toàn trang (vẫn hợp lệ nhưng mất vị trí cụ thể).
    """
    boxes = _as_sequence(boxes)
    texts = _as_sequence(texts)
    scores = _as_sequence(scores)
    lines: list[OcrLine] = []
    for index, text in enumerate(texts):
        clean = (text or "").strip()
        if not clean:
            continue
        score = float(scores[index]) if index < len(scores) else 0.0
        if score < min_confidence:
            continue
        box = boxes[index] if index < len(boxes) else None
        bbox = _normalize_bbox(box, width, height) if box is not None else (0.0, 0.0, 1.0, 1.0)
        lines.append(
            OcrLine(
                text=clean,
                confidence=round(min(1.0, max(0.0, score)), 6),
                bbox=bbox,
            )
        )
    return lines


def ocr_pdf_pages(
    pdf_bytes: bytes, page_numbers: list[int], *, dpi: int | None = None
) -> list[OcrPage]:
    """OCR các trang được chỉ định (số trang 1-based, theo thứ tự tăng dần).

    Trả danh sách `OcrPage`; trang không đọc được chữ có `lines=[]`. Lỗi engine
    thành `OcrError`. Không gọi mạng, không ghi file.
    """
    import numpy as np

    settings = get_settings()
    if not settings.ocr_enabled:
        raise OcrError("OCR_DISABLED", "OCR chưa được bật trên hệ thống này.")
    engine_name = (settings.ocr_engine or "").strip().lower()
    if engine_name not in SUPPORTED_ENGINES:
        raise OcrError(
            "OCR_NOT_CONFIGURED",
            f"Engine OCR «{settings.ocr_engine}» không được hỗ trợ "
            f"(hợp lệ: {', '.join(SUPPORTED_ENGINES)}).",
        )
    if not engine_available(engine_name):
        raise OcrError(
            "OCR_NOT_CONFIGURED",
            f"Engine OCR «{engine_name}» chưa được cài trên server "
            "(xem backend/requirements-ocr*.txt).",
        )

    resolution = max(72, int(dpi if dpi is not None else settings.ocr_dpi))
    engine = _get_engine(engine_name, settings.ocr_lang)
    deadline = time.monotonic() + max(1.0, settings.ocr_timeout_seconds)
    min_confidence = max(0.0, min(1.0, settings.ocr_min_confidence))

    results: list[OcrPage] = []
    for number in page_numbers:
        if time.monotonic() > deadline:
            raise OcrError(
                "OCR_TIMEOUT",
                "OCR vượt quá thời gian cho phép; hãy giảm số trang hoặc DPI.",
                retryable=True,
            )
        image = _render_page(pdf_bytes, number, resolution)
        try:
            if engine_name == "vietocr":
                boxes, width, height = _detect_boxes(image)
                texts, scores = _recognize_vietocr(engine, image, boxes)
            else:
                width, height = image.size
                array = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()  # RGB → BGR
                raw = engine(array)
                boxes = getattr(raw, "boxes", None)
                # `txts`/`scores` cũng có thể là numpy array ⇒ không dùng `or ()`.
                texts = getattr(raw, "txts", None)
                texts = () if texts is None else texts
                scores = getattr(raw, "scores", None)
                scores = () if scores is None else scores
        except OcrError:
            raise
        except Exception as exc:  # noqa: BLE001 — lỗi engine phải thành mã ổn định
            raise OcrError(
                "OCR_FAILED", f"Engine OCR lỗi: {type(exc).__name__}.", retryable=True
            ) from exc

        lines = build_lines(
            boxes,
            texts,
            scores,
            width=width,
            height=height,
            min_confidence=min_confidence,
        )
        results.append(OcrPage(page_number=number, lines=lines, width=width, height=height))

    logger.info(
        "ocr pages done pages=%s lines=%s dpi=%s engine=%s",
        len(results),
        sum(len(page.lines) for page in results),
        resolution,
        engine_name,
    )
    return results
