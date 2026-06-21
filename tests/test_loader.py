import pytest
import sqlite3
from app.ingest.loader import load_file, load_directory
from app.db.schema import create_tables


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def redirect_processed_dir(tmp_path, monkeypatch):
    """Redirect PROCESSED_DIR to tmp_path to avoid polluting data/processed/."""
    processed = tmp_path / "processed"
    processed.mkdir()
    monkeypatch.setattr("app.ingest.loader.PROCESSED_DIR", processed)


class TestLoadFile:
    def test_inserts_valid_rows(self, mem_db, tmp_path):
        path = tmp_path / "jan.csv"
        path.write_text(
            "data;descricao;valor\n01/01/2024;CONTINENTE;-45,30\n15/01/2024;SALARIO;1800,00",
            encoding="utf-8",
        )
        count = load_file(path, mem_db)
        assert count == 2
        assert mem_db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2

    def test_skips_already_imported(self, mem_db, tmp_path):
        mem_db.execute(
            "INSERT INTO transactions (date, description, amount, source_file) "
            "VALUES ('2024-01-01', 'X', -1, 'test.csv')"
        )
        mem_db.commit()
        path = tmp_path / "test.csv"
        path.write_text("data;descricao;valor\n02/01/2024;UBER;-12,50", encoding="utf-8")
        assert load_file(path, mem_db) == 0
        assert path.exists()  # file was NOT moved

    def test_moves_file_to_processed(self, mem_db, tmp_path):
        path = tmp_path / "jan.csv"
        path.write_text("data;descricao;valor\n01/01/2024;CONTINENTE;-45,30", encoding="utf-8")
        load_file(path, mem_db)
        assert not path.exists()

    def test_skipped_rows_stored(self, mem_db, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(
            "data;descricao;valor\nnot-a-date;CONTINENTE;-45,30\n01/01/2024;UBER;-12,50",
            encoding="utf-8",
        )
        count = load_file(path, mem_db)
        assert count == 1
        skipped = mem_db.execute("SELECT * FROM skipped_rows").fetchall()
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "data inválida"

    def test_unsupported_format_raises(self, mem_db, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("content")
        with pytest.raises(ValueError, match="Formato não suportado"):
            load_file(path, mem_db)


class TestLoadDirectory:
    def test_loads_multiple_csv(self, mem_db, tmp_path):
        for name, line in [("jan.csv", "01/01/2024;A;-10,00"), ("fev.csv", "01/02/2024;B;-20,00")]:
            (tmp_path / name).write_text(f"data;descricao;valor\n{line}", encoding="utf-8")
        assert load_directory(tmp_path, mem_db) == 2

    def test_empty_directory_returns_zero(self, mem_db, tmp_path):
        assert load_directory(tmp_path, mem_db) == 0

    def test_ignores_unsupported_files(self, mem_db, tmp_path):
        (tmp_path / "readme.txt").write_text("ignore")
        (tmp_path / "jan.csv").write_text("data;descricao;valor\n01/01/2024;A;-10,00")
        assert load_directory(tmp_path, mem_db) == 1
