CREATE_SKIPPED_ROWS = """
CREATE TABLE IF NOT EXISTS skipped_rows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT    NOT NULL,
    date_raw        TEXT,
    description_raw TEXT,
    amount_raw      TEXT,
    reason          TEXT    NOT NULL,
    raw_text        TEXT,
    imported_at     TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,
    description TEXT    NOT NULL,
    amount      REAL    NOT NULL,
    category    TEXT    NOT NULL DEFAULT 'Outros',
    source_file TEXT    NOT NULL,
    raw_text    TEXT,
    imported_at TEXT    NOT NULL DEFAULT (datetime('now')),
    verified    INTEGER NOT NULL DEFAULT 0
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_verified ON transactions(verified)",
]


CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'viewer',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""


def create_tables(conn):
    conn.execute(CREATE_TRANSACTIONS)
    conn.execute(CREATE_SKIPPED_ROWS)
    conn.execute(CREATE_USERS)
    # Migration: add verified column to existing databases before creating indexes
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    for idx in CREATE_INDEXES:
        conn.execute(idx)
    conn.commit()
