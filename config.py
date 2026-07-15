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

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL = "llama-3.3-70b-versatile"
