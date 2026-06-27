CREATE_SKIPPED_ROWS = """
CREATE TABLE IF NOT EXISTS skipped_rows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT    NOT NULL,
    date_raw        TEXT,
    description_raw TEXT,
    amount_raw      TEXT,
    reason          TEXT    NOT NULL,
    raw_text        TEXT,
    space           TEXT    NOT NULL DEFAULT 'joint',
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
    space       TEXT    NOT NULL DEFAULT 'joint',
    imported_at TEXT    NOT NULL DEFAULT (datetime('now')),
    verified    INTEGER NOT NULL DEFAULT 0
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_verified ON transactions(verified)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_space ON transactions(space)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_patrimony ON transactions(patrimony_id)",
]

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    email                TEXT    NOT NULL UNIQUE,
    password_hash        TEXT    NOT NULL,
    role                 TEXT    NOT NULL DEFAULT 'viewer',
    active               INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_PATRIMONY = """
CREATE TABLE IF NOT EXISTS patrimony (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    space          TEXT    NOT NULL,
    label          TEXT    NOT NULL,
    amount         REAL    NOT NULL,
    category       TEXT    NOT NULL DEFAULT 'Outros',
    reference_date TEXT    NOT NULL DEFAULT (date('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""


def create_tables(conn):
    conn.execute(CREATE_TRANSACTIONS)
    conn.execute(CREATE_SKIPPED_ROWS)
    conn.execute(CREATE_USERS)
    conn.execute(CREATE_PATRIMONY)
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN space TEXT NOT NULL DEFAULT 'joint'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE skipped_rows ADD COLUMN space TEXT NOT NULL DEFAULT 'joint'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN patrimony_id INTEGER REFERENCES patrimony(id) ON DELETE SET NULL")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE patrimony ADD COLUMN reference_date TEXT NOT NULL DEFAULT '2024-01-01'")
    except Exception:
        pass
    for idx in CREATE_INDEXES:
        conn.execute(idx)
    conn.commit()
