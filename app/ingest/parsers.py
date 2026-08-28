"""Raw file parsers — return a list of dicts with raw column names intact."""
import re
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
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(path, sep=None, engine="python", dtype=str,
                             encoding=encoding, encoding_errors="strict")
            return _extract_rows(df, path)
        except (UnicodeDecodeError, ValueError):
            continue
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


def _parse_bankintercard(path: Path, full_text: str) -> list[dict] | None:
    """Detect and parse Bankintercard credit card statements."""
    if "bankintercard" not in full_text.lower():
        return None

    # Extract end year/month from period header e.g. "2026/06/11 a 2026/07/10"
    end_m = re.search(r"\d{4}/\d{2}/\d{2}\s+a\s+(\d{4})/(\d{2})/\d{2}", full_text)
    if end_m:
        end_year, end_month = int(end_m.group(1)), int(end_m.group(2))
    else:
        import datetime as _dt
        _now = _dt.datetime.now()
        end_year, end_month = _now.year, _now.month

    rows = []
    in_section = False

    for line in full_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        if "resumo e detalhe das transaç" in line.lower():
            in_section = True
            continue
        if not in_section:
            continue
        if re.search(r"o sinal \(-\)|pagamentos efetuados no período", line, re.IGNORECASE):
            break

        # Transaction rows: DD/MM  DD/MM  DESCRIPTION  VALUE
        m = re.match(r"^(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(.+?)\s+([-\d.,]+)$", line)
        if not m:
            continue

        date_dd_mm = m.group(2)  # Data Mov.
        desc = m.group(3).strip()
        val_raw = m.group(4)

        # Infer year: if month > end_month, transaction is from end_year - 1
        try:
            month = int(date_dd_mm.split("/")[1])
            year = end_year if month <= end_month else end_year - 1
        except (ValueError, IndexError):
            year = end_year

        # Flip sign: statement shows expenses as positive; finance analyzer uses negative
        if val_raw.startswith("-"):
            val_raw = val_raw[1:]  # Refund/reimbursement → positive
        else:
            val_raw = f"-{val_raw}"  # Expense → negative

        rows.append({
            "date": f"{date_dd_mm}/{year}",
            "description": desc,
            "amount_raw": val_raw,
        })

    return rows if rows else None


def _parse_trade_republic(path: Path, full_text: str) -> list[dict] | None:
    """Detect and parse Trade Republic bank account statements (PDF).

    pdfplumber scatters each transaction across 3 lines due to the multi-column
    PDF layout, so we anchor on the line that ends with two € amounts
    (transaction amount + running balance) and gather date/description from the
    surrounding lines.
    """
    if "trade republic" not in full_text.lower():
        return None

    tx_start = re.search(r"ACCOUNT TRANSACTIONS", full_text)
    if not tx_start:
        return None

    tx_text = full_text[tx_start.end():]
    tx_end = re.search(r"BALANCE OVERVIEW|TRANSACTIONS OVERVIEW|NOTES ON THE", tx_text)
    if tx_end:
        tx_text = tx_text[:tx_end.start()]

    _MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    day_month_re = re.compile(rf"^(\d{{1,2}} {_MONTHS})\s*(.*)$")
    year_re = re.compile(r"^(\d{4})\s*(.*)$")
    # A transaction line ends with exactly two € amounts: tx_amount + balance
    amount_line_re = re.compile(r"^(.*?)\s+€([\d,]+\.\d{2})\s+€([\d,]+\.\d{2})\s*$")

    _KNOWN_TYPES = ("Transfer", "Interest", "Fee", "Withdrawal", "Deposit", "Dividend")

    from datetime import datetime as _dt

    lines = [l.strip() for l in tx_text.split("\n") if l.strip()]
    rows: list[dict] = []
    i = 0

    while i < len(lines):
        am = amount_line_re.match(lines[i])
        if not am:
            i += 1
            continue

        leading = am.group(1).strip()
        tx_amount_str = am.group(2).replace(",", "")
        # am.group(3) is the running balance — ignored

        # Day/month is on the previous line (may carry extra description text)
        day_month = prev_extra = ""
        if i > 0:
            dm = day_month_re.match(lines[i - 1])
            if dm:
                day_month = dm.group(1)
                prev_extra = dm.group(2).strip()

        # Year is on the next line (may carry extra description text)
        year = next_extra = ""
        if i + 1 < len(lines):
            ym = year_re.match(lines[i + 1])
            if ym:
                year = ym.group(1)
                next_extra = ym.group(2).strip()

        if not day_month or not year:
            i += 1
            continue

        # Extract type and the description portion on the amount line
        tx_type = desc_on_amount_line = ""
        for known in _KNOWN_TYPES:
            if leading.startswith(known):
                tx_type = known
                desc_on_amount_line = leading[len(known):].strip()
                break
        if not tx_type:
            tx_type = leading.split()[0] if leading else "Transfer"
            desc_on_amount_line = leading[len(tx_type):].strip()

        # Reconstruct full description from all three line fragments
        desc = " ".join(p for p in [prev_extra, desc_on_amount_line, next_extra] if p).strip()
        if not desc:
            desc = tx_type

        try:
            date = _dt.strptime(f"{day_month} {year}", "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            i += 1
            continue

        amount = float(tx_amount_str)
        desc_lower = desc.lower()
        tx_type_lower = tx_type.lower()

        if "outgoing" in desc_lower or tx_type_lower in ("fee", "withdrawal"):
            amount = -abs(amount)
        else:
            amount = abs(amount)

        row: dict = {
            "date": date,
            "description": f"Trade Republic - {desc}",
            "amount": round(amount, 2),
        }

        if tx_type_lower == "interest":
            row["category"] = "Rendimentos"
            row["subcategory"] = "Juros"

        rows.append(row)
        i += 2  # consume amount line + year line

    return rows if rows else None


def _parse_trading212(path: Path, full_text: str) -> list[dict] | None:
    """Detect and parse Trading 212 activity statements."""
    if "trading 212" not in full_text.lower():
        return None

    import calendar
    from collections import defaultdict

    MONTH_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

    deposits = []
    payouts = []
    interest_by_month: dict[str, float] = defaultdict(float)
    dividends = []
    bonuses = []

    # Parse dated transaction lines: YYYY-MM-DD HH:MM:SS Description €amount
    tx_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\s+(.+?)\s+€(-?[\d,]+\.\d{2})$"
    )
    for line in full_text.split("\n"):
        m = tx_re.match(line.strip())
        if not m:
            continue
        date_str = m.group(1)
        desc = m.group(2).strip()
        amount = float(m.group(3).replace(",", ""))
        dl = desc.lower()

        if "deposit" in dl:
            deposits.append((date_str, desc, -amount))
        elif "payout" in dl:
            payouts.append((date_str, desc, -amount))
        elif "interest on cash" in dl:
            interest_by_month[date_str[:7]] += amount
        elif "free equity" in dl or "free share" in dl:
            bonuses.append((date_str, desc, amount))

    # Parse dividend table rows (different format):
    # INSTRUMENT ISIN COUNTRY HOLDINGS DD.MM.YYYY HH:MM ... €net_amount
    div_re = re.compile(
        r"^(.+?)\s+([A-Z]{2}[A-Z0-9]{10})\s+\S+\s+[\d.]+\s+(\d{2}\.\d{2}\.\d{4})\s+\d{2}:\d{2}.+€([\d.]+)$"
    )
    seen_div_dates: set[str] = set()
    for line in full_text.split("\n"):
        m = div_re.match(line.strip())
        if not m:
            continue
        instrument = m.group(1).strip()
        isin = m.group(2)
        try:
            from datetime import datetime as _dt
            date_str = _dt.strptime(m.group(3), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        net_amount = float(m.group(4))
        key = f"{date_str}_{isin}"
        if key not in seen_div_dates:
            seen_div_dates.add(key)
            dividends.append((date_str, f"Dividendo - {instrument} ({isin})", net_amount))

    rows: list[dict] = []

    for date_str, desc, amount in deposits:
        rows.append({"date": date_str, "description": f"Trading 212 - {desc}", "amount": -amount})

    for date_str, desc, amount in payouts:
        rows.append({"date": date_str, "description": f"Trading 212 - {desc}", "amount": -amount})

    for month_key in sorted(interest_by_month):
        year, month = int(month_key[:4]), int(month_key[5:])
        last_day = calendar.monthrange(year, month)[1]
        rows.append({
            "date": f"{year}-{month:02d}-{last_day:02d}",
            "description": f"Trading 212 - Interest on Cash ({MONTH_PT[month - 1]} {year})",
            "amount": round(interest_by_month[month_key], 2),
            "category": "Rendimentos",
            "subcategory": "Interest on Cash",
        })

    for date_str, desc, amount in dividends:
        rows.append({
            "date": date_str,
            "description": f"Trading 212 - {desc}",
            "amount": amount,
            "category": "Rendimentos",
            "subcategory": "Dividendos",
        })

    for date_str, desc, amount in bonuses:
        rows.append({
            "date": date_str,
            "description": f"Trading 212 - {desc}",
            "amount": amount,
            "category": "Rendimentos",
            "subcategory": "Bonus Trading 212",
        })

    return rows if rows else None


def _parse_igcp_certificados(path: Path, full_text: str) -> list[dict] | None:
    """Detect and parse IGCP Extrato de Conta Aforro (Certificados de Aforro)."""
    text_lower = full_text.lower()
    if "certificados de aforro" not in text_lower and "conta aforro" not in text_lower:
        return None

    series_m = re.search(r"\bSérie\s+([A-Z])(?=\s|$)", full_text, re.MULTILINE)
    series = f" Série {series_m.group(1).upper()}" if series_m else ""

    # Rows: DD-MM-YYYY  SubscrNr  UnitValue  Units  TotalValue
    row_re = re.compile(
        r"^(\d{2}-\d{2}-\d{4})\s+\d+\s+[\d,]+\s+([\d.]+)\s+[\d.,]+$",
        re.MULTILINE,
    )

    from datetime import datetime as _dt
    rows = []
    for m in row_re.finditer(full_text):
        try:
            date_iso = _dt.strptime(m.group(1), "%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        units = int(m.group(2).replace(".", "").replace(",", ""))
        rows.append({
            "date": date_iso,
            "description": f"IGCP - Certificados de Aforro{series}",
            "amount": float(units),
            "category": "Poupanças",
            "subcategory": "Certificados de Aforro",
        })

    return rows if rows else None


def parse_pdf(path: Path) -> list[dict]:
    import io
    import pdfplumber
    from app.ingest.payslip_parser import parse_payslip

    result = parse_payslip(path)
    if result is not None:
        for row in result:
            row['auto_verify'] = True
            row.setdefault('category', 'Remunerações')
        return result

    all_rows = []
    header = None

    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # Bankintercard credit card statement
        result = _parse_bankintercard(path, text)
        if result is not None:
            return result

        # Trading 212 activity statement
        result = _parse_trading212(path, text)
        if result is not None:
            return result

        # Trade Republic bank account statement
        result = _parse_trade_republic(path, text)
        if result is not None:
            return result

        # IGCP Certificados de Aforro
        result = _parse_igcp_certificados(path, text)
        if result is not None:
            return result

        # Pass 1: try table extraction (works for most machine-generated PDFs)
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


def _parse_edenred_html(html_content: str, path: Path, cutoff=...) -> list[dict]:
    """Parse MyEdenred HTML — shared by parse_html (with cutoff) and parse_mhtml (no cutoff)."""
    from bs4 import BeautifulSoup
    from datetime import datetime

    if cutoff is ...:
        m = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
        cutoff = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

    soup = BeautifulSoup(html_content, "html.parser")
    table_body = soup.find("div", class_="table-body")
    if not table_body:
        raise ValueError(f"{path.name}: estrutura HTML não reconhecida (div.table-body não encontrada).")

    rows = []
    for row in table_body.find_all("div", class_="no-animations"):
        date_div   = row.find("div", class_="data-wrapper")
        desc_div   = row.find("div", class_="description-wrapper")
        amount_div = row.find("div", class_=lambda c: c and "amount-wrapper" in c and "balance-wrapper" not in c)

        if not (date_div and desc_div and amount_div):
            continue

        date_raw = date_div.get_text(strip=True)
        dm = re.search(r"(\d{2}/\d{2}/\d{4})", date_raw)
        if not dm:
            continue

        if cutoff and datetime.strptime(dm.group(1), "%d/%m/%Y") < cutoff:
            continue

        rows.append({
            "date": dm.group(1),
            "description": desc_div.get_text(strip=True),
            "amount_raw": amount_div.get_text(strip=True),
        })

    if not rows:
        raise ValueError(f"{path.name}: nenhuma transação encontrada no HTML.")

    return rows


def parse_html(path: Path) -> list[dict]:
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return _parse_edenred_html(f.read(), path)
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return _parse_edenred_html(f.read(), path)


def parse_mhtml(path: Path) -> list[dict]:
    import email as _email

    with open(path, "rb") as f:
        msg = _email.message_from_binary_file(f)

    for part in msg.walk():
        if part.get_content_type() == "text/html":
            charset = part.get_content_charset() or "utf-8"
            html_content = part.get_payload(decode=True).decode(charset, errors="replace")
            return _parse_edenred_html(html_content, path, cutoff=None)

    raise ValueError(f"{path.name}: não foi possível extrair HTML do ficheiro MHTML.")


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
