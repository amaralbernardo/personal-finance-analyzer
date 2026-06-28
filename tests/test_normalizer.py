import pytest
from app.ingest.normalizer import _parse_date, _parse_amount, normalize


class TestParseDate:
    def test_pt_slash(self):
        assert _parse_date("25/01/2024") == "2024-01-25"

    def test_pt_dash(self):
        assert _parse_date("25-01-2024") == "2024-01-25"

    def test_iso(self):
        assert _parse_date("2024-01-25") == "2024-01-25"

    def test_pt_short_year(self):
        assert _parse_date("25/01/24") == "2024-01-25"

    def test_pt_dot(self):
        assert _parse_date("25.01.2024") == "2024-01-25"

    def test_whitespace(self):
        assert _parse_date("  2024-01-25  ") == "2024-01-25"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_date("not-a-date")


class TestParseAmount:
    def test_en_format(self):
        assert _parse_amount("1234.56") == 1234.56

    def test_pt_format(self):
        assert _parse_amount("1.234,56") == 1234.56

    def test_negative(self):
        assert _parse_amount("-45.30") == -45.30

    def test_negative_pt(self):
        assert _parse_amount("-1.234,56") == -1234.56

    def test_currency_symbol(self):
        assert _parse_amount("€ 99,90") == 99.90

    def test_simple_comma(self):
        assert _parse_amount("45,30") == 45.30

    def test_integer(self):
        assert _parse_amount("100") == 100.0


class TestNormalize:
    def test_csv_rows(self):
        rows = [
            {"date": "01/01/2024", "description": "Supermercado", "amount_raw": "-50,00"},
            {"date": "02/01/2024", "description": "Salário",      "amount_raw": "1500,00"},
        ]
        valid, skipped = normalize(rows, "test.csv")
        assert len(valid) == 2
        assert valid[0]["date"] == "2024-01-01"
        assert valid[0]["amount"] == -50.0
        assert valid[1]["amount"] == 1500.0
        assert valid[0]["source_file"] == "test.csv"
        assert skipped == []

    def test_ofx_rows(self):
        rows = [{"date": "2024-01-10", "description": "Uber", "amount": -12.5}]
        valid, skipped = normalize(rows, "bank.ofx")
        assert len(valid) == 1
        assert valid[0]["amount"] == -12.5
        assert skipped == []

    def test_empty_description_skipped(self):
        rows = [{"date": "01/01/2024", "description": "   ", "amount_raw": "-10,00"}]
        valid, skipped = normalize(rows, "test.csv")
        assert valid == []
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "descrição vazia"

    def test_bad_date_skipped(self):
        rows = [{"date": "not-a-date", "description": "Test", "amount_raw": "-10,00"}]
        valid, skipped = normalize(rows, "test.csv")
        assert valid == []
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "data inválida"
