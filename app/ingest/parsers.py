"""Raw file parsers — return a list of dicts with raw column names intact."""
import pandas as pd
from pathlib import Path


# Common column-name aliases used by Portuguese banks
_DATE_COLS = {"data", "date", "data mov.", "data valor", "data movimento", "data de movimento",
              "data de conclusão", "data de conclusao", "data de início", "data de inicio"}
_DESC_COLS = {"descricao", "descrição", "description", "movimento", "designação", "designacao"}
_AMT_COLS  = {"valor", "amount", "montante", "importância", "importancia"}
_DEB_COLS  = {"débito", "debito", "debit"}
_CRE_COLS  = {"crédito", "credito", "credit"}


_ALL_KNOWN = _DATE_COLS | _DESC_COLS | _AMT_COLS | _DEB_COLS | _CRE_COLS


_DATE_PRIORITY = ["data de conclusão", "data de conclusao", "data valor", "data mov.",
                  "data movimento", "data de movimento", "data de início", "data de inicio",
                  "data", "date"]


def _find_col(columns: list[str], candidates: set[str]) -> str | None:
    cols_lower = {col.strip().lower(): col for col in columns}
    if candidates is _DATE_COLS:
        for priority in _DATE_PRIORITY:
            if priority in cols_lower:
                return cols_lower[priority]
    for col in columns:
        if col.strip().lower() in candidates:
            return col
    return None


def _find_header_row(path: Path, sep: str, encoding: str) -> int:
    """Return the 0-based row index where the real column headers appear.

    Scans each row looking for at least 2 cells whose lowercased value matches
    a known column alias. Returns 0 if no such row is found (standard layout).
    """
    raw = pd.read_csv(path, sep=sep, dtype=str, encoding=encoding,
                      header=None, encoding_errors="replace")
    for idx, row in raw.iterrows():
        matches = sum(
            1 for cell in row.dropna()
            if str(cell).strip().lower() in _ALL_KNOWN
        )
        if matches >= 2:
            return int(idx)
    return 0


def parse_csv(path: Path) -> list[dict]:
    df = pd.read_csv(path, sep=None, engine="python", dtype=str, encoding_errors="replace")
    return _extract_rows(df, path)


def parse_xlsx(path: Path) -> list[dict]:
    engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
    try:
        df = pd.read_excel(path, dtype=str, engine=engine)
        return _extract_rows(df, path)
    except Exception:
        pass

    # Fallback 1: tab-separated text saved as .xls (e.g. Novo Banco Net24)
    # Some banks prepend metadata rows — find the real header row first.
    for enc in ("latin-1", "cp1252", "utf-8"):
        try:
            header_row = _find_header_row(path, sep="\t", encoding=enc)
            df = pd.read_csv(path, sep="\t", dtype=str, encoding=enc,
                             skiprows=header_row, encoding_errors="replace")
            return _extract_rows(df, path)
        except Exception:
            continue

    # Fallback 2: HTML table saved as .xls
    try:
        tables = pd.read_html(path, encoding="utf-8")
        if tables:
            return _extract_rows(tables[0].astype(str), path)
    except Exception:
        pass

    raise ValueError(f"{path.name}: não foi possível ler como Excel, TSV nem HTML.")


def parse_ofx(path: Path) -> list[dict]:
    from ofxparse import OfxParser

    with open(path, "rb") as f:
        ofx = OfxParser.parse(f)

    rows = []
    for account in ofx.accounts:
        for txn in account.statement.transactions:
            rows.append({
                "date": txn.date.strftime("%Y-%m-%d"),
                "description": txn.memo or txn.payee or "",
                "amount": float(txn.amount),
            })
    return rows


def parse_pdf(path: Path) -> list[dict]:
    import io
    import pdfplumber
    from app.ingest.payslip_parser import parse_payslip

    result = parse_payslip(path)
    if result is not None:
        return result

    all_rows = []
    header = None

    # Pass 1: try table extraction (works for most machine-generated PDFs)
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                if not table:
                    continue
                first_row = [str(c).strip().lower() if c else "" for c in table[0]]
                has_header = sum(1 for cell in first_row if cell in _ALL_KNOWN) >= 2
                if has_header:
                    header = [str(c).strip() if c else f"col_{i}" for i, c in enumerate(table[0])]
                    all_rows.extend(table[1:])
                else:
                    all_rows.extend(table)

    if header and all_rows:
        df = pd.DataFrame(all_rows, columns=header).astype(str)
        return _extract_rows(df, path)

    # Pass 2: text extraction with fixed-width parsing
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    if not text.strip():
        raise ValueError(
            f"{path.name}: PDF sem texto extraível — pode ser um scan/imagem."
        )

    lines = [l for l in text.split("\n") if l.strip()]
    header_idx = None
    for i, line in enumerate(lines):
        cells = line.strip().lower().split()
        if sum(1 for cell in cells if cell in _ALL_KNOWN) >= 2:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(
            f"{path.name}: não foi possível identificar colunas (data/descrição/valor) no PDF."
        )

    block = "\n".join(lines[header_idx:])
    try:
        df = pd.read_fwf(io.StringIO(block), dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        return _extract_rows(df, path)
    except Exception as exc:
        raise ValueError(f"{path.name}: falha ao processar texto do PDF: {exc}")


def _extract_rows(df: pd.DataFrame, path: Path) -> list[dict]:
    cols = list(df.columns)
    date_col = _find_col(cols, _DATE_COLS)
    desc_col = _find_col(cols, _DESC_COLS)
    amt_col  = _find_col(cols, _AMT_COLS)
    deb_col  = _find_col(cols, _DEB_COLS)
    cre_col  = _find_col(cols, _CRE_COLS)

    if not date_col or not desc_col:
        raise ValueError(
            f"{path.name}: não foi possível identificar colunas de data/descrição. "
            f"Colunas encontradas: {cols}"
        )

    rows = []
    for _, row in df.iterrows():
        # Amount: prefer single amount column; fall back to debit/credit pair
        if amt_col:
            amount_raw = str(row[amt_col])
        elif deb_col and cre_col:
            deb = str(row[deb_col]).strip()
            cre = str(row[cre_col]).strip()
            # Debit as negative, credit as positive
            if deb and deb not in ("", "nan"):
                amount_raw = f"-{deb}"
            else:
                amount_raw = cre
        else:
            raise ValueError(f"{path.name}: não foi possível identificar coluna de valor.")

        rows.append({
            "date": str(row[date_col]),
            "description": str(row[desc_col]),
            "amount_raw": amount_raw,
        })
    return rows
