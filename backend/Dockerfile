FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# P4.3 — OCR là optional và NẶNG (onnxruntime + opencv). Chỉ cài khi build với
# `--build-arg INSTALL_OCR=true`; mặc định image không có OCR và cờ OCR_ENABLED
# bật nhầm sẽ fail-fast `OCR_NOT_CONFIGURED` thay vì âm thầm bỏ qua.
ARG INSTALL_OCR=false
COPY requirements-ocr.txt .
RUN if [ "$INSTALL_OCR" = "true" ]; then pip install --no-cache-dir -r requirements-ocr.txt; fi

COPY . .

EXPOSE 8000

# Chạy Alembic migration trước khi start app (idempotent — đã ở head thì no-op)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
