"""
Extracts text from uploaded study material: PDF, TXT, and images (OCR).
"""

import os

ALLOWED_EXTENSIONS = {"pdf", "txt", "jpg", "jpeg", "png"}


def allowed_file(filename):
    if "." not in filename:
        return False
    return get_extension(filename) in ALLOWED_EXTENSIONS


def get_extension(filename):
    return filename.rsplit(".", 1)[1].lower()


def extract_pdf(path):
    import fitz  # PyMuPDF
    text = ""
    document = fitz.open(path)
    try:
        for page in document:
            text += page.get_text()
    finally:
        document.close()
    return text.strip()


def extract_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


def is_blurry(path, threshold=100.0):
    try:
        import cv2
    except ImportError:
        return False
    image = cv2.imread(path)
    if image is None:
        return True
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    return variance < threshold


def extract_image_text(path):
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise Exception(
            "Image text extraction requires 'pytesseract' and 'Pillow', and the "
            "tesseract-ocr system package."
        ) from e

    if is_blurry(path):
        raise Exception("Uploaded image is too blurry to read. Please upload a clearer image.")

    try:
        image = Image.open(path)
        text = pytesseract.image_to_string(image)
    except Exception as e:
        raise Exception(f"OCR failed ({e}).") from e

    return text.strip()


def extract_text(path):
    extension = get_extension(path)
    if extension == "pdf":
        return extract_pdf(path)
    if extension == "txt":
        return extract_txt(path)
    if extension in ("jpg", "jpeg", "png"):
        return extract_image_text(path)
    return ""
