"""Orchestrates file detection, parsing, normalisation, and DB persistence."""
import sqlite3
from pathlib import Path

from app.ingest.parsers import parse_csv, parse_xlsx, parse_ofx, parse_pdf, parse_html, parse_mhtml
from app.ingest.normalizer import normalize

PROCESSED_DIR = Path(__file__).parents[2] / "data" / "processed"

_PARSERS = {
    ".csv":  parse_csv,
    ".xlsx": parse_xlsx,
    ".xls":  parse_xlsx,
    ".ofx":  parse_ofx,
    ".qfx":  parse_ofx,
    ".pdf":  parse_pdf,
    ".html":  parse_html,
    ".mhtml": parse_mhtml,
}


def _already_loaded(conn: sqlite3.Connection, source_file: str, space: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM transactions WHERE source_file = ? AND space = ? LIMIT 1",
        (source_file, space),
    ).fetchone()
    return row is not None


def _insert(conn: sqlite3.Connection, transactions: list[dict], space: str) -> int:
    for tx in transactions:
        tx['space'] = space

    regular = [tx for tx in transactions if not tx.get('auto_verify')]
    auto_verified = [tx for tx in transactions if tx.get('auto_verify')]

    plain    = [tx for tx in regular if 'category' not in tx]
    pre_cat  = [tx for tx in regular if 'category' in tx]

    if plain:
        conn.executemany(
            "INSERT INTO transactions (date, description, amount, source_file, space) "
            "VALUES (:date, :description, :amount, :source_file, :space)",
            plain,
        )
    if pre_cat:
        for tx in pre_cat:
            tx.setdefault('subcategory', None)
        conn.executemany(
            "INSERT INTO transactions "
            "(date, description, amount, source_file, space, category, subcategory) "
            "VALUES (:date, :description, :amount, :source_file, :space, :category, :subcategory)",
            pre_cat,
        )
    if auto_verified:
        for tx in auto_verified:
            tx.setdefault('category', 'Outros')
            tx.setdefault('subcategory', None)
        conn.executemany(
            "INSERT INTO transactions "
            "(date, description, amount, source_file, space, category, subcategory, verified) "
            "VALUES (:date, :description, :amount, :source_file, :space, :category, :subcategory, 1)",
            auto_verified,
        )

    conn.commit()
    return len(transactions)


def _insert_skipped(conn: sqlite3.Connection, skipped_rows: list[dict], space: str) -> None:
    for row in skipped_rows:
        row['space'] = space
    conn.executemany(
        """
        INSERT INTO skipped_rows (source_file, date_raw, description_raw, amount_raw, reason, space)
        VALUES (:source_file, :date_raw, :description_raw, :amount_raw, :reason, :space)
        """,
        skipped_rows,
    )
    conn.commit()


def load_file(path: Path, conn: sqlite3.Connection,
              space: str = 'joint', processed_dir: Path = None) -> int:
    if processed_dir is None:
        processed_dir = PROCESSED_DIR

    suffix = path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise ValueError(f"Formato não suportado: {suffix}")

    source_file = path.name
    if _already_loaded(conn, source_file, space):
        print(f"  [saltar] {source_file} já foi importado anteriormente.")
        path.unlink(missing_ok=True)
        return 0

    print(f"  [a importar] {source_file} …")
    try:
        raw_rows = parser(path)
    except Exception as exc:
        print(f"  [erro] {source_file}: {exc}")
        conn.execute(
            """INSERT INTO skipped_rows (source_file, date_raw, description_raw, amount_raw, reason, space)
               VALUES (?, '', '', '', ?, ?)""",
            (source_file, str(exc), space),
        )
        conn.commit()
        return 0

    valid, skipped = normalize(raw_rows, source_file)

    if skipped:
        _insert_skipped(conn, skipped, space)
        print(f"  [aviso] {source_file}: {len(skipped)} linha(s) ignorada(s).")

    if not valid and not skipped:
        print(f"  [aviso] {source_file}: nenhuma transação encontrada.")
        return 0

    count = _insert(conn, valid, space) if valid else 0

    path.unlink()
    print(f"  [ok] {source_file}: {count} transações importadas.")
    return count


def load_directory(directory: Path, conn: sqlite3.Connection,
                   space: str = 'joint', processed_dir: Path = None) -> int:
    total = 0
    files = [f for f in sorted(directory.iterdir()) if f.suffix.lower() in _PARSERS]
    if not files:
        print(f"Nenhum ficheiro suportado em {directory}")
        return 0
    for f in files:
        total += load_file(f, conn, space=space, processed_dir=processed_dir)
    return total
