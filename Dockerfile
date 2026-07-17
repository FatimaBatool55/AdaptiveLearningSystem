FROM python:3.12-slim

# System dependencies:
# - tesseract-ocr: required by services/file_service.py for image (JPG/PNG)
#   text extraction. This is the main reason to use Docker instead of
#   Render's native Python buildpack, which can't install arbitrary system
#   packages — with this Dockerfile, image upload/OCR actually works here,
#   which it never could on Vercel's serverless runtime.
# - libgl1 / libglib2.0-0: runtime libraries opencv-python-headless needs
#   even in "headless" mode on some minimal base images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render's filesystem is a normal writable container filesystem (unlike
# Vercel's read-only-except-/tmp setup), so these can just be regular
# folders created at build time.
RUN mkdir -p uploads instance

ENV PYTHONUNBUFFERED=1

# Render sets $PORT at runtime and expects the app to bind to it — shell
# form (not exec/JSON-array form) is required here so $PORT actually gets
# expanded by the shell instead of being passed through literally.
CMD gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 120 app:app
