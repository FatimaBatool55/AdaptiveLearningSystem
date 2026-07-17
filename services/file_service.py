"""
Extracts text from uploaded study material: PDF, DOCX, PPTX, TXT and
(optionally) images via OCR.

Image OCR (pytesseract + opencv) needs the system `tesseract-ocr` binary
installed, which isn't guaranteed on every host. To avoid crashing the whole
app when those optional dependencies/binaries are missing, they are imported
lazily and a clear error is raised only if the user actually uploads an image.
"""

import os
import shutil
import subprocess
import tempfile

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "jpg", "jpeg", "png"}


def allowed_file(filename):
    if "." not in filename:
        return False
    return get_extension(filename) in ALLOWED_EXTENSIONS


def get_extension(filename):
    return filename.rsplit(".", 1)[1].lower()


# ---------------------------------------------------------------------
# Legacy Office format conversion (.doc / .ppt -> .docx / .pptx)
# ---------------------------------------------------------------------

# Common install locations, checked if plain "soffice" isn't found on PATH.
# Windows installers (including winget) frequently update PATH in a way that
# already-running processes — including an IDE's terminal that was merely
# reopened rather than the whole IDE restarted — never pick up. Searching
# these known paths directly sidesteps that entire class of problem. Set the
# LIBREOFFICE_PATH environment variable to override with a custom location.
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


def _convert_with_libreoffice(path, target_format):
    """
    Converts a legacy binary Office file (.doc/.ppt) to its modern XML
    equivalent (.docx/.pptx) using headless LibreOffice, so the existing
    python-docx/python-pptx extractors can handle it normally afterwards.

    This is more reliable than dedicated legacy-format text extractors like
    catppt/catdoc (from the catdoc package) — those were tested against a
    genuine legacy .ppt file and returned completely empty output despite
    exiting with a success code, making them unsafe to depend on. LibreOffice
    conversion correctly recovered the text in the same test.

    Requires the `soffice` (LibreOffice) binary — see _find_soffice() above
    for how it's located, and the Dockerfile for the Docker/Linux install.
    """
    soffice_path = _find_soffice()
    if not soffice_path:
        raise Exception(
            "Converting legacy Office files requires LibreOffice, which wasn't found on "
            f"this system (checked PATH and common install locations). Please save this "
            f"file as .{target_format} manually and re-upload, or set the LIBREOFFICE_PATH "
            "environment variable to your soffice.exe location."
        )

    output_dir = tempfile.mkdtemp()
    try:
        result = subprocess.run(
            [soffice_path, "--headless", "--convert-to", target_format, "--outdir", output_dir, path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise Exception(
            f"Found a LibreOffice path ({soffice_path}) but couldn't execute it. "
            f"Please save this file as .{target_format} manually and re-upload."
        )
    except subprocess.TimeoutExpired:
        raise Exception("Converting this file timed out. Try a smaller or simpler file.")

    if result.returncode != 0:
        raise Exception(
            f"Could not convert this file: {result.stderr.strip() or 'unknown LibreOffice error'}"
        )

    base_name = os.path.splitext(os.path.basename(path))[0]
    converted_path = os.path.join(output_dir, f"{base_name}.{target_format}")
    if not os.path.exists(converted_path):
        raise Exception("Conversion did not produce the expected output file.")

    return converted_path


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
        # Legacy .doc is OLE2 binary format, not the zip/XML format
        # python-docx expects — convert to .docx via LibreOffice first.
        converted = _convert_with_libreoffice(path, "docx")
        return extract_docx(converted)
    if extension == "pptx":
        return extract_ppt(path)
    if extension == "ppt":
        # Same story as .doc above: python-pptx only understands the newer
        # OOXML .pptx format, not legacy binary .ppt. Convert first.
        converted = _convert_with_libreoffice(path, "pptx")
        return extract_ppt(converted)
    if extension == "txt":
        return extract_txt(path)
    if extension in ("jpg", "jpeg", "png"):
        return extract_image_text(path)

    return ""