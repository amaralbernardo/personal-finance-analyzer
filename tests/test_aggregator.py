from app.analysis.aggregator import (
    total_balance, total_income, total_expenses,
    by_category, by_month, top_expenses, summary,
)
from app.categorize.engine import recategorize_all


def test_total_income(db):
    assert total_income(db) == 3600.00  # 2 × 1800


def test_total_expenses(db):
    expenses = total_expenses(db)
    # 45.30 + 12.50 + 15.99 + 38.70 + 22.00 + 60.00 = 194.49
    assert round(expenses, 2) == 194.49


def test_total_balance(db):
    balance = total_balance(db)
    assert round(balance, 2) == round(3600.00 - 194.49, 2)


def test_by_category_keys(db):
    recategorize_all(db)
    rows = by_category(db)
    assert isinstance(rows, list)
    for row in rows:
        assert "category" in row
        assert "total" in row
        assert "count" in row
        assert row["total"] >= 0


def test_by_category_sorted_desc(db):
    recategorize_all(db)
    rows = by_category(db)
    totals = [r["total"] for r in rows]
    assert totals == sorted(totals, reverse=True)


def test_by_month_chronological(db):
    months = [r["month"] for r in by_month(db)]
    assert months == sorted(months)


def test_by_month_values(db):
    months = {r["month"]: r for r in by_month(db)}
    jan = months["2024-01"]
    assert jan["income"] == 1800.00
    assert round(jan["expenses"], 2) == round(45.30 + 12.50 + 15.99, 2)


def test_top_expenses_count(db):
    top = top_expenses(db, n=5)
    assert len(top) <= 5


def test_top_expenses_sorted(db):
    top = top_expenses(db)
    amounts = [r["amount"] for r in top]
    assert amounts == sorted(amounts, reverse=True)


def test_summary_keys(db):
    s = summary(db)
    for key in ("balance", "total_income", "total_expenses", "by_category", "by_month", "top_expenses"):
        assert key in s


def test_empty_db_returns_zeros():
    import sqlite3
    from app.db.schema import create_tables
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    assert total_balance(conn) == 0.0
    assert total_income(conn) == 0.0
    assert total_expenses(conn) == 0.0
    assert by_category(conn) == []
    assert by_month(conn) == []
