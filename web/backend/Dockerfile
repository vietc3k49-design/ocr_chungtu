# Backend API + worker KIDO OCR (Linux). Pipeline tools/ KHÔNG nằm trong image: mount read-only gốc repo vào /repo.
FROM python:3.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    KIDO_REPO_ROOT=/repo \
    # Dùng ĐÚNG traineddata của máy Windows đã đo các chỉ số (tessdata_fast; sha256 trong tessdata/SHA256SUMS)
    TESSDATA_PREFIX=/opt/tessdata

# Tesseract 5.5 (Debian trixie) — Windows đo bằng 5.5.0.20241111. Không cài gói ngôn ngữ của Debian.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 libgl1 curl \
 && rm -rf /var/lib/apt/lists/*

COPY tessdata/ /opt/tessdata/
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . /app

# Chạy bằng user không phải root
RUN useradd -m -u 1000 kido && mkdir -p /data && chown -R kido:kido /data /app
USER kido
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
