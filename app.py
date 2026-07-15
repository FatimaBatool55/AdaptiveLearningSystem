import os
import sys

# Vercel's Python runtime loads this file via importlib.util.spec_from_file_location
# directly (see /var/task/_vendor/vercel_runtime/resolver.py), which does NOT add
# this file's own directory to sys.path the way a normal `python app.py` invocation
# does. Without this, sibling packages (models/, routes/, services/) fail to import
# on Vercel with "ModuleNotFoundError: No module named 'models'" even though they
# sit right next to this file in the deployed bundle. This line is a harmless no-op
# when running locally or on any other host (the directory is usually already on
# sys.path there), so it's safe to always include.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from sqlalchemy import inspect, text
from config import Config
from models import db


def _auto_add_missing_columns(app):
    """
    db.create_all() only creates tables that don't exist yet — it never adds
    new columns to a table that's already there. If you add a field to a
    model (e.g. is_weak_practice) after the table was first created against
    Supabase/Postgres, the app will crash with 'UndefinedColumn' on the next
    insert. This scans each model's expected columns against what's actually
    in the database and ALTERs in anything missing, so that never happens.

    This is a pragmatic safety net for a small app, NOT a replacement for
    real migrations (Alembic/Flask-Migrate) on a production project with
    many contributors.
    """
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    for mapper in db.Model.registry.mappers:
        model = mapper.class_
        table = model.__table__
        if table.name not in existing_tables:
            continue  # brand new table — create_all() already handled it

        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}

        for column in table.columns:
            if column.name in existing_columns:
                continue

            col_type = column.type.compile(dialect=db.engine.dialect)
            nullable = "" if column.nullable else " NOT NULL" if column.default is not None or column.server_default is not None else ""
            # Keep it simple/safe: always add as nullable first to avoid failing
            # on existing rows, regardless of the model's nullable setting.
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            try:
                with db.engine.begin() as conn:
                    conn.execute(text(ddl))
                app.logger.warning(f"[auto-migrate] Added missing column {table.name}.{column.name}")
            except Exception as e:  # noqa: BLE001
                app.logger.error(f"[auto-migrate] Failed to add {table.name}.{column.name}: {e}")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not os.environ.get("VERCEL"):
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "instance"), exist_ok=True)

    db.init_app(app)

    from routes.main import main_bp
    app.register_blueprint(main_bp)

    with app.app_context():
        # Creates any missing tables automatically (safe/idempotent).
        # Works against Supabase/Postgres as well as local SQLite fallback.
        db.create_all()
        # Adds any missing columns on tables that already existed.
        _auto_add_missing_columns(app)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
