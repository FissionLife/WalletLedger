import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Base

logger = logging.getLogger(__name__)

IS_SQLITE = settings.database_url.startswith("sqlite")


def _build_engine():
    """SQLite for local/single-user use, PostgreSQL for production; chosen by config."""
    if IS_SQLITE:
        database = make_url(settings.database_url).database
        if database and database != ":memory:":
            Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")  # off by default: needed for ON DELETE CASCADE
            cur.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return eng

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )


engine = _build_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def describe_database() -> str:
    """Safe-to-log description of the active backend (never includes the password)."""
    if IS_SQLITE:
        return f"SQLite ({make_url(settings.database_url).database})"
    return f"PostgreSQL ({engine.url.render_as_string(hide_password=True)})"


# Columns added after the first release. `create_all` never alters an existing table, and the project has
# no migration tool, so a database made by an older version gets these added here (safe to repeat).
_ADDED_COLUMNS = [("transactions", "entered_at", "TIMESTAMP")]


def _add_missing_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    for table, column, ddl_type in _ADDED_COLUMNS:
        if table not in inspector.get_table_names():
            continue
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        logger.info("Database upgraded: added %s.%s", table, column)


def init_db():
    """Initializes tables in database."""
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    logger.info("Database ready: %s", describe_database())


def get_db():
    """Dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
