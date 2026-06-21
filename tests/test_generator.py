import re
import sqlite3
import pytest
from app.db.schema import create_tables
from app.reports.generator import generate


@pytest.fixture
def sample_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    conn.executemany(
        "INSERT INTO transactions (date, description, amount, category, source_file, verified) "
        "VALUES (?,?,?,?,?,1)",
        [
            ("2024-01-05", "CONTINENTE", -45.30, "Alimentação", "test.csv"),
            ("2024-01-10", "UBER", -12.50, "Transportes", "test.csv"),
            ("2024-01-15", "SALARIO", 1800.00, "Outros", "test.csv"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


class TestGenerate:
    def test_creates_html_file(self, sample_db, tmp_path):
        path = generate(sample_db, output_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".html"

    def test_filename_format(self, sample_db, tmp_path):
        path = generate(sample_db, output_dir=tmp_path)
        assert re.match(r"report_\d{8}_\d{6}\.html", path.name)

    def test_html_contains_income(self, sample_db, tmp_path):
        path = generate(sample_db, output_dir=tmp_path)
        assert "1800" in path.read_text(encoding="utf-8")

    def test_html_contains_expense_category(self, sample_db, tmp_path):
        path = generate(sample_db, output_dir=tmp_path)
        assert "Alimentação" in path.read_text(encoding="utf-8")

    def test_empty_db_generates_without_error(self, tmp_path):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        path = generate(conn, output_dir=tmp_path)
        assert path.exists()
        conn.close()

    def test_creates_output_dir_if_missing(self, sample_db, tmp_path):
        out = tmp_path / "new_reports"
        assert not out.exists()
        generate(sample_db, output_dir=out)
        assert out.exists()
