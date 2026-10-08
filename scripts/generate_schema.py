"""Regenerate sql/schema.sql from the SQLAlchemy models (app/models.py).

Run with:  uv run python scripts/generate_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app.models import Base  # noqa: E402

HEADER = """-- WalletLedger schema (PostgreSQL 16+), generated from app/models.py.
-- Do not edit by hand: run `uv run python scripts/generate_schema.py` after model changes.
-- The app also creates missing tables on startup (init_db), so this file is for review,
-- manual setup (`psql -f sql/schema.sql`) and documentation.
"""


def render() -> str:
    dialect = postgresql.dialect()
    parts = [HEADER]
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        ddl = "\n".join(line.rstrip().replace("\t", "    ") for line in ddl.splitlines())
        parts.append(ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1) + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            idx = str(CreateIndex(index).compile(dialect=dialect)).strip()
            idx = idx.replace("INDEX ", "INDEX IF NOT EXISTS ", 1)
            parts.append(idx + ";")
        parts.append("")
    return "\n".join(parts)


def main() -> None:
    path = os.path.join(os.path.dirname(__file__), "..", "sql", "schema.sql")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render())
    print(f"Wrote {os.path.normpath(path)} ({len(Base.metadata.sorted_tables)} tables)")


if __name__ == "__main__":
    main()
