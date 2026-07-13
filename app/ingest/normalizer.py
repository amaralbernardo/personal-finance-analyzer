"""Converts raw parser output to the canonical transaction schema."""
import re
from datetime import datetime


def _parse_amount(raw: str) -> float:
    """Handles both PT format (1.234,56) and EN format (1234.56)."""
    s = raw.strip().replace(" ", "").replace("\xa0", "")
    # Remove currency symbols
    s = re.sub(r"[€$£]", "", s)
    negative = s.startswith("-")
    s = s.lstrip("-+")

    # Detect PT format: has dot as thousands sep and comma as decimal sep
    if re.search(r"\d\.\d{3},\d", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        # EN or ambiguous: just replace comma with dot
        s = s.replace(",", ".")

    value = float(s)
    return -value if negative else value


def _parse_date(raw: str) -> str:
    """Returns ISO date string YYYY-MM-DD. Tries common PT/EU formats."""
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Formato de data não reconhecido: '{raw}'")


def normalize(rows: list[dict], source_file: str) -> tuple[list[dict], list[dict]]:
    """
    Returns (valid_transactions, skipped_rows).

    valid_transactions: ready for DB insert {date, description, amount, source_file}
    skipped_rows: {source_file, date_raw, description_raw, amount_raw, reason}

    OFX rows already have parsed date/amount; CSV/XLSX rows carry amount_raw.
    """
    valid = []
    skipped = []

    for row in rows:
        date_raw = str(row.get("date", ""))
        description_raw = str(row.get("description", ""))
        amount_raw = str(row.get("amount_raw", row.get("amount", "")))

        if not description_raw.strip():
            skipped.append({
                "source_file": source_file,
                "date_raw": date_raw,
                "description_raw": description_raw,
                "amount_raw": amount_raw,
                "reason": "descrição vazia",
            })
            continue

        # Parse date
        try:
            date = date_raw if "amount" in row else _parse_date(date_raw)
        except ValueError:
            skipped.append({
                "source_file": source_file,
                "date_raw": date_raw,
                "description_raw": description_raw.strip(),
                "amount_raw": amount_raw,
                "reason": "data inválida",
            })
            continue

        # Parse amount
        try:
            amount = float(row["amount"]) if "amount" in row else _parse_amount(amount_raw)
        except (ValueError, KeyError):
            skipped.append({
                "source_file": source_file,
                "date_raw": date_raw,
                "description_raw": description_raw.strip(),
                "amount_raw": amount_raw,
                "reason": "valor inválido",
            })
            continue

        valid.append({
            "date": date,
            "description": description_raw.strip(),
            "amount": amount,
            "source_file": source_file,
        })

    return valid, skipped
