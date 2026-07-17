FROM python:3.12-slim

# System dependencies:
# - tesseract-ocr: required by services/file_service.py for image (JPG/PNG)
#   text extraction. This is the main reason to use Docker instead of
#   Render's native Python buildpack, which can't install arbitrary system
#   packages — with this Dockerfile, image upload/OCR actually works here,
#   which it never could on Vercel's serverless runtime.
# - libreoffice-writer / libreoffice-impress: used to convert legacy binary
#   .doc/.ppt files (pre-2007 Office formats) to modern .docx/.pptx before
#   extracting text. Tested against a dedicated legacy-format extractor
#   (catdoc/catppt) first — it silently returned empty output on a genuine
#   .ppt file, so LibreOffice conversion is used instead despite the larger
#   image size, since it actually works reliably.
# - libgl1 / libglib2.0-0: runtime libraries opencv-python-headless needs
#   even in "headless" mode on some minimal base images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libreoffice-writer \
    libreoffice-impress \
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

# Render sets $PORT at runtime and expects the app to bind to it. Hugging
# Face Spaces does NOT set $PORT and instead expects the app on port 7860 by
# default — the ${PORT:-7860} fallback below makes this one Dockerfile work
# on both platforms without changes. Shell form (not exec/JSON-array form)
# is required so the variable actually gets expanded by the shell.
CMD gunicorn --bind 0.0.0.0:${PORT:-7860} --workers 2 --threads 4 --timeout 120 app:app