import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _normalize_db_url(url: str) -> str:
    """Supabase/Heroku-style URLs sometimes start with postgres:// or plain
    postgresql://, both of which make SQLAlchemy default to the psycopg2
    driver. This project installs psycopg (v3) instead — because it has
    reliable prebuilt wheels on Windows, whereas psycopg2-binary can fail
    to build from source on newer Python versions. Force the +psycopg
    driver explicitly so SQLAlchemy doesn't try to import psycopg2."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    _db_url = os.environ.get("DATABASE_URL")
    if not _db_url:
        # Safe local fallback so the app still boots without Supabase configured
        _db_url = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'quiz.db')}"
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(_db_url)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Vercel's filesystem is read-only everywhere except /tmp. Detect that
    # environment (Vercel sets VERCEL=1) and write uploads/reports there
    # instead of a local uploads/ folder, which would fail to write on Vercel.
    IS_VERCEL = bool(os.environ.get("VERCEL"))
    if IS_VERCEL:
        UPLOAD_FOLDER = "/tmp/uploads"
    else:
        UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

    # Vercel Hobby/Pro serverless functions hard-reject any request body over
    # ~4.5MB with a 413 PAYLOAD_TOO_LARGE *before our code ever runs* — no
    # amount of Flask config can raise that ceiling there. Other hosts (Render,
    # Snap, etc.) have no such platform-level limit, so give them a much more
    # generous default and only shrink it specifically when running on Vercel.
    #
    # UPLOAD_LIMIT_MB is the number we advertise to the user (e.g. in the
    # "file too large" flash message). The actual Flask MAX_CONTENT_LENGTH is
    # set a few MB higher than that, because the raw file isn't the only thing
    # in the request body — multipart/form-data encoding adds boundary
    # strings and headers, and the other form fields (education level,
    # question type, notes text, etc.) count too. Without this headroom, a
    # file that's *exactly* at the advertised limit gets rejected even though
    # it technically fits the promise made to the user.
    UPLOAD_LIMIT_MB = 4 if IS_VERCEL else 50
    MAX_CONTENT_LENGTH = (UPLOAD_LIMIT_MB + 5) * 1024 * 1024

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL = "llama-3.3-70b-versatile"