"""
Extracts text from uploaded study material: PDF, DOC, DOCX, TXT, and
(optionally) images via OCR.

Image OCR (pytesseract + opencv) needs the system `tesseract-ocr` binary
installed, which isn't guaranteed on every host. To avoid crashing the whole
app when those optional dependencies/binaries are missing, they are imported
lazily and a clear error is raised only if the user actually uploads an image.

Legacy .doc (pre-2007 binary Word format) needs LibreOffice installed to
convert it to .docx first — python-docx only understands the modern XML
format. See _find_soffice() below and the Dockerfile for the install.
"""

import os
import shutil
import subprocess
import tempfile

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt", "jpg", "jpeg", "png"}


def allowed_file(filename):
    if "." not in filename:
        return False
    return get_extension(filename) in ALLOWED_EXTENSIONS


def get_extension(filename):
    return filename.rsplit(".", 1)[1].lower()

# Legacy .doc conversion (.doc -> .docx via LibreOffice)


_LIBREOFFICE_CANDIDATES = [
    os.environ.get("LIBREOFFICE_PATH"),
    "soffice",  # PATH lookup (works on Linux/Docker, and Windows if PATH is fresh)
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/opt/libreoffice/program/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def _find_soffice():
    for candidate in _LIBREOFFICE_CANDIDATES:
        if not candidate:
            continue
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        elif shutil.which(candidate):
            return shutil.which(candidate)
    return None


def _convert_doc_to_docx(path):
    """Converts a legacy .doc file to .docx using headless LibreOffice, so
    python-docx can read it normally afterward."""
    soffice_path = _find_soffice()
    if not soffice_path:
        raise Exception(
            "Converting legacy .doc files requires LibreOffice, which wasn't found on "
            "this system. Please save this file as .docx manually and re-upload, or set "
            "the LIBREOFFICE_PATH environment variable to your soffice.exe location."
        )

    output_dir = tempfile.mkdtemp()
    try:
        result = subprocess.run(
            [soffice_path, "--headless", "--convert-to", "docx", "--outdir", output_dir, path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise Exception(
            f"Found a LibreOffice path ({soffice_path}) but couldn't execute it. "
            "Please save this file as .docx manually and re-upload."
        )
    except subprocess.TimeoutExpired:
        raise Exception("Converting this file timed out. Try a smaller or simpler file.")

    if result.returncode != 0:
        raise Exception(
            f"Could not convert this file: {result.stderr.strip() or 'unknown LibreOffice error'}"
        )

    base_name = os.path.splitext(os.path.basename(path))[0]
    converted_path = os.path.join(output_dir, f"{base_name}.docx")
    if not os.path.exists(converted_path):
        raise Exception("Conversion did not produce the expected output file.")

    return converted_path


# PDF

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


# DOCX

def extract_docx(path):
    from docx import Document
    document = Document(path)
    return "\n".join(p.text for p in document.paragraphs).strip()


# TXT

def extract_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


# Image OCR

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


# Universal extraction dispatcher

def extract_text(path):
    extension = get_extension(path)

    if extension == "pdf":
        return extract_pdf(path)
    if extension == "docx":
        return extract_docx(path)
    if extension == "doc":
        converted = _convert_doc_to_docx(path)
        return extract_docx(converted)
    if extension == "txt":
        return extract_txt(path)
    if extension in ("jpg", "jpeg", "png"):
        return extract_image_text(path)

    return ""
