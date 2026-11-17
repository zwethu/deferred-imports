"""Create or open a repository's event log, index/<repo>.sqlite.

The tables are defined in schema.sql and explained in docs/schema.md.

    con = schema.connect(Path("index/netbox.sqlite"))
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2  # keep equal to `PRAGMA user_version` at the end of schema.sql
SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database at `path`. A new file gets the tables; an old schema version is refused."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")  # per connection, so it cannot live in schema.sql
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        con.executescript(SCHEMA_SQL.read_text())
    elif version != SCHEMA_VERSION:
        con.close()
        raise RuntimeError(f"{path} has schema version {version}, this code expects "
                           f"{SCHEMA_VERSION}: delete it and mine the repository again")
    return con
