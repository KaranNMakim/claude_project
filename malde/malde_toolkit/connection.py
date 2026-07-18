"""Database connection helper for MALDE."""
import os
import sqlite3
from functools import lru_cache
import pandas as pd

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "malde.db")


class MaldeDB:
    """Thin wrapper around a SQLite connection with pandas helpers."""

    def __init__(self, path: str = DEFAULT_DB_PATH):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Database not found at {path}. Run db/load_sqlite.py first.")
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row

    # --- raw access -------------------------------------------------------
    def query(self, sql: str, params=None) -> pd.DataFrame:
        """Run a read query and return a DataFrame."""
        return pd.read_sql_query(sql, self.con, params=params or [])

    def scalar(self, sql: str, params=None):
        cur = self.con.execute(sql, params or [])
        row = cur.fetchone()
        return row[0] if row else None

    def execute(self, sql: str, params=None):
        """Run a write statement (used by self-healing agents)."""
        cur = self.con.execute(sql, params or [])
        self.con.commit()
        return cur.rowcount

    # --- metadata ---------------------------------------------------------
    def tables(self) -> list[str]:
        rows = self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        return [r[0] for r in rows]

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@lru_cache(maxsize=4)
def get_db(path: str = DEFAULT_DB_PATH) -> MaldeDB:
    """Cached singleton connection (convenient for agent tools)."""
    return MaldeDB(path)
