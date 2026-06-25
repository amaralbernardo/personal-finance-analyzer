"""Shared pytest fixtures."""
import sqlite3
import pytest

from app.db.schema import create_tables


@pytest.fixture
def db():
    """In-memory SQLite DB with schema and sample transactions."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    rows = [
        ("2024-01-05", "CONTINENTE MODELO",       -45.30, "Outros",       "jan.csv"),
        ("2024-01-10", "UBER TRIP",                -12.50, "Outros",       "jan.csv"),
        ("2024-01-15", "SALARIO EMPRESA XYZ",     1800.00, "Outros",       "jan.csv"),
        ("2024-01-20", "NETFLIX.COM",              -15.99, "Outros",       "jan.csv"),
        ("2024-02-03", "PINGO DOCE",               -38.70, "Outros",       "fev.csv"),
        ("2024-02-14", "FARMACIA CENTRAL",         -22.00, "Outros",       "fev.csv"),
        ("2024-02-28", "SALARIO EMPRESA XYZ",     1800.00, "Outros",       "fev.csv"),
        ("2024-03-01", "GALP COMBUSTIVEL",         -60.00, "Outros",       "mar.csv"),
    ]
    conn.executemany(
        "INSERT INTO transactions (date, description, amount, category, source_file) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    yield conn
    conn.close()
