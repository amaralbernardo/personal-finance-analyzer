import textwrap
import pytest
import openpyxl
from pathlib import Path
from app.ingest.parsers import parse_csv, parse_xlsx, parse_ofx


@pytest.fixture
def tmp_csv(tmp_path):
    """Returns a factory that writes a CSV string to a temp file."""
    def _make(content: str, filename: str = "test.csv") -> Path:
        p = tmp_path / filename
        p.write_text(textwrap.dedent(content).strip(), encoding="utf-8")
        return p
    return _make


class TestParseCsv:
    def test_semicolon_separator(self, tmp_csv):
        path = tmp_csv("""
            Data;Descrição;Valor
            01/01/2024;CONTINENTE;-45,30
            15/01/2024;SALARIO;1800,00
        """)
        rows = parse_csv(path)
        assert len(rows) == 2
        assert rows[0]["description"] == "CONTINENTE"
        assert rows[0]["amount_raw"] == "-45,30"

    def test_comma_separator(self, tmp_csv):
        path = tmp_csv("""
            date,description,amount
            2024-01-01,UBER,-12.50
            2024-01-15,SALARY,1800.00
        """)
        rows = parse_csv(path)
        assert len(rows) == 2
        assert rows[1]["description"] == "SALARY"

    def test_debit_credit_columns(self, tmp_csv):
        path = tmp_csv("""
            Data;Descrição;Débito;Crédito
            01/01/2024;SUPERMERCADO;50,00;
            15/01/2024;SALARIO;;1800,00
        """)
        rows = parse_csv(path)
        assert rows[0]["amount_raw"] == "-50,00"
        assert rows[1]["amount_raw"] == "1800,00"

    def test_missing_date_column_raises(self, tmp_csv):
        path = tmp_csv("""
            Foo;Bar
            a;b
        """)
        with pytest.raises(ValueError, match="data"):
            parse_csv(path)

    def test_raw_text_populated(self, tmp_csv):
        path = tmp_csv("""
            data;descricao;valor
            01/01/2024;TEST;-10,00
        """)
        rows = parse_csv(path)
        assert rows[0]["raw_text"] != ""


class TestParseXlsx:
    def test_standard_xlsx(self, tmp_path):
        path = tmp_path / "extrato.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Data", "Descrição", "Valor"])
        ws.append(["01/01/2024", "CONTINENTE", "-45,30"])
        ws.append(["15/01/2024", "SALARIO", "1800,00"])
        wb.save(path)

        rows = parse_xlsx(path)
        assert len(rows) == 2
        assert rows[0]["description"] == "CONTINENTE"
        assert rows[0]["amount_raw"] == "-45,30"
        assert rows[1]["description"] == "SALARIO"

    def test_xlsx_debit_credit_columns(self, tmp_path):
        path = tmp_path / "extrato.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Data", "Descrição", "Débito", "Crédito"])
        ws.append(["01/01/2024", "SUPERMERCADO", "50,00", ""])
        ws.append(["15/01/2024", "SALARIO", "", "1800,00"])
        wb.save(path)

        rows = parse_xlsx(path)
        assert rows[0]["amount_raw"] == "-50,00"
        assert rows[1]["amount_raw"] == "1800,00"


class TestParseTsvAsXls:
    """Tab-separated files saved with .xls extension (Novo Banco Net24 export)."""

    def test_tsv_fallback(self, tmp_path):
        path = tmp_path / "extrato.xls"
        path.write_text(
            "Data\tDescrição\tValor\n01/01/2024\tCONTINENTE\t-45,30\n15/01/2024\tSALARIO\t1800,00",
            encoding="latin-1",
        )
        rows = parse_xlsx(path)
        assert len(rows) == 2
        assert rows[0]["description"] == "CONTINENTE"

    def test_tsv_with_metadata_rows(self, tmp_path):
        """Metadata rows before the header are skipped automatically."""
        path = tmp_path / "extrato.xls"
        path.write_text(
            "Banco X - Extrato\t\t\nPeriodo: 01/2024\t\t\nData\tDescrição\tValor\n01/01/2024\tUBER\t-12,50",
            encoding="latin-1",
        )
        rows = parse_xlsx(path)
        assert len(rows) == 1
        assert rows[0]["description"] == "UBER"


class TestParseOfx:
    OFX_CONTENT = """\
OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<LANGUAGE>ENG
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1001
<STMTRS>
<CURDEF>EUR
<BANKACCTFROM>
<BANKID>123456
<ACCTID>00001234
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20240101
<DTEND>20240131
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20240105
<TRNAMT>-45.30
<FITID>20240105001
<MEMO>CONTINENTE
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20240115
<TRNAMT>1800.00
<FITID>20240115001
<MEMO>SALARIO
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1754.70
<DTASOF>20240131
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""

    @pytest.fixture
    def ofx_file(self, tmp_path):
        path = tmp_path / "extrato.ofx"
        path.write_text(self.OFX_CONTENT, encoding="ascii")
        return path

    def test_parses_two_transactions(self, ofx_file):
        rows = parse_ofx(ofx_file)
        assert len(rows) == 2

    def test_parses_description(self, ofx_file):
        rows = parse_ofx(ofx_file)
        descriptions = {r["description"] for r in rows}
        assert "CONTINENTE" in descriptions
        assert "SALARIO" in descriptions

    def test_parses_amount(self, ofx_file):
        rows = parse_ofx(ofx_file)
        by_desc = {r["description"]: r["amount"] for r in rows}
        assert by_desc["CONTINENTE"] == pytest.approx(-45.30)
        assert by_desc["SALARIO"] == pytest.approx(1800.00)

    def test_parses_date(self, ofx_file):
        rows = parse_ofx(ofx_file)
        dates = {r["date"] for r in rows}
        assert "2024-01-05" in dates
        assert "2024-01-15" in dates
