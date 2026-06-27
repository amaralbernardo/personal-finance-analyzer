"""Payslip PDF parser — extracts salary transactions from EDP and Accenture formats."""
import re
from calendar import monthrange
from datetime import date
from pathlib import Path


_PT_MONTHS = {
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
    'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12,
}
_EN_MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
}


def _last_day(year: int, month: int) -> str:
    return date(year, month, monthrange(year, month)[1]).strftime('%Y-%m-%d')


def is_payslip(text: str) -> bool:
    markers = ['RECIBO MENSAL', 'TOTAL BRUTO', 'REMUNERAT. STATEMENT', 'TOTALS EUR', 'Net value:']
    return sum(1 for m in markers if m in text) >= 2


def _parse_edp(text: str, source: str) -> list[dict]:
    # Date: prefer DATA DE PAGAMENTO dd.mm.yyyy, fallback to month name
    m = re.search(r'DATA DE PAGAMENTO\s*[\n\r]+\s*(\d{2})\.(\d{2})\.(\d{4})', text)
    if m:
        date_val = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    else:
        m = re.search(
            r'(Janeiro|Fevereiro|Mar[çc]o|Abril|Maio|Junho|Julho|Agosto|'
            r'Setembro|Outubro|Novembro|Dezembro)\s+(\d{4})',
            text, re.IGNORECASE,
        )
        if not m:
            raise ValueError(f"{source}: não foi possível identificar o período do recibo EDP.")
        month = _PT_MONTHS.get(m.group(1).lower())
        date_val = _last_day(int(m.group(2)), month)

    rows = []

    m = re.search(r'Total\s+Bruto\s+([\d.,]+)', text, re.IGNORECASE)
    if m:
        rows.append({
            'date': date_val,
            'description': 'Salário Bruto',
            'amount_raw': m.group(1),
            'raw_text': 'EDP RECIBO MENSAL - Salário Bruto',
        })

    m = re.search(r'Total\s+L[íi]quido\s+([\d.,]+)', text, re.IGNORECASE)
    if m:
        rows.append({
            'date': date_val,
            'description': 'Salário Líquido',
            'amount_raw': m.group(1),
            'raw_text': 'EDP RECIBO MENSAL - Salário Líquido',
        })

    if not rows:
        raise ValueError(f"{source}: não foi possível extrair valores do recibo EDP.")

    return rows


def _parse_accenture(text: str, source: str) -> list[dict]:
    # Date from "Period: June 2026"
    m = re.search(r'Period:\s+(\w+)\s+(\d{4})', text, re.IGNORECASE)
    if not m:
        raise ValueError(f"{source}: não foi possível identificar o período do recibo Accenture.")
    month = _EN_MONTHS.get(m.group(1).lower())
    if not month:
        raise ValueError(f"{source}: mês não reconhecido '{m.group(1)}'.")
    date_val = _last_day(int(m.group(2)), month)

    rows = []

    # Gross: first value after "TOTALS EUR"
    m = re.search(r'TOTALS\s+EUR\s+([\d.,]+)', text)
    if m:
        rows.append({
            'date': date_val,
            'description': 'Salário Bruto',
            'amount_raw': m.group(1),
            'raw_text': 'Accenture REMUNERAT. STATEMENT - Salário Bruto',
        })

    # Net transfer (prefer Net transf. over Net value)
    m = re.search(r'Net\s+transf\.:\s*([\d.,]+)', text, re.IGNORECASE)
    if not m:
        m = re.search(r'Net\s+value:\s*([\d.,]+)', text, re.IGNORECASE)
    if m:
        rows.append({
            'date': date_val,
            'description': 'Salário Líquido',
            'amount_raw': m.group(1),
            'raw_text': 'Accenture REMUNERAT. STATEMENT - Salário Líquido',
        })

    # Transferred Euroticket Card
    m = re.search(r'Transferred\s+Euroticket\s+Card:\s*([\d.,]+)', text, re.IGNORECASE)
    if m:
        rows.append({
            'date': date_val,
            'description': 'Cartão Refeição',
            'amount_raw': m.group(1),
            'raw_text': 'Accenture REMUNERAT. STATEMENT - Cartão Refeição',
        })

    # Share Plan: "Share Plan XXXX mm/yyyy  rate  deduction_amount"
    m = re.search(r'Share\s+Plan\s+\S+\s+\d{2}/\d{4}\s+[\d.,]+\s+([\d.,]+)', text)
    if m:
        rows.append({
            'date': date_val,
            'description': 'Ações',
            'amount_raw': m.group(1),
            'raw_text': 'Accenture REMUNERAT. STATEMENT - Ações',
        })

    if not rows:
        raise ValueError(f"{source}: não foi possível extrair valores do recibo Accenture.")

    return rows


def parse_payslip(path: Path):
    """Detect payslip format and extract transactions. Returns None if not a payslip."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)

    if not text.strip() or not is_payslip(text):
        return None

    if 'RECIBO MENSAL' in text:
        return _parse_edp(text, path.name)
    if 'REMUNERAT. STATEMENT' in text or 'TOTALS EUR' in text:
        return _parse_accenture(text, path.name)

    raise ValueError(f"{path.name}: formato de recibo não reconhecido.")
