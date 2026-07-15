"""
Extracts text from uploaded study material: PDF, DOCX, PPTX, TXT and
(optionally) images via OCR.

Image OCR (pytesseract + opencv) needs the system `tesseract-ocr` binary
installed, which isn't guaranteed on every host. To avoid crashing the whole
app when those optional dependencies/binaries are missing, they are imported
lazily and a clear error is raised only if the user actually uploads an image.
"""

import os

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "jpg", "jpeg", "png"}


def allowed_file(filename):
    if "." not in filename:
        return False
    return get_extension(filename) in ALLOWED_EXTENSIONS


def get_extension(filename):
    return filename.rsplit(".", 1)[1].lower()


# ---------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------
def extract_docx(path):
    from docx import Document
    document = Document(path)
    return "\n".join(p.text for p in document.paragraphs).strip()


# ---------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------
def extract_ppt(path):
    from pptx import Presentation
    prs = Presentation(path)
    lines = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text:
                lines.append(shape.text)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------
def extract_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


# ---------------------------------------------------------------------
# Image OCR (optional — requires pytesseract + the tesseract-ocr binary)
# ---------------------------------------------------------------------
def is_blurry(path, threshold=100.0):
    try:
        import cv2
    except ImportError:
        return False  # can't check blur without opencv — don't block extraction

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
            "tesseract-ocr system package. Install them or upload a PDF/DOCX/TXT instead."
        ) from e

    if is_blurry(path):
        raise Exception("Uploaded image is too blurry to read. Please upload a clearer image.")

    try:
        image = Image.open(path)
        text = pytesseract.image_to_string(image)
    except Exception as e:
        raise Exception(
            f"OCR failed ({e}). Make sure the tesseract-ocr binary is installed on this system."
        ) from e

    return text.strip()


# ---------------------------------------------------------------------
# Universal extraction dispatcher
# ---------------------------------------------------------------------
def extract_text(path):
    extension = get_extension(path)

    if extension == "pdf":
        return extract_pdf(path)
    if extension == "docx":
        return extract_docx(path)
    if extension == "doc":
        # Legacy .doc isn't supported by python-docx; best-effort fallback.
        try:
            return extract_docx(path)
        except Exception:
            raise Exception(
                "Legacy .doc files aren't fully supported. Please save as .docx and re-upload."
            )
    if extension in ("ppt", "pptx"):
        return extract_ppt(path)
    if extension == "txt":
        return extract_txt(path)
    if extension in ("jpg", "jpeg", "png"):
        return extract_image_text(path)

    return ""
