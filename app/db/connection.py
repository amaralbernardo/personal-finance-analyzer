import sqlite3
from pathlib import Path

from app.db.schema import create_tables

DB_PATH = Path(__file__).parents[2] / "data" / "finance.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn
