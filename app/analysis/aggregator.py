"""Aggregation queries over the transactions table."""
import sqlite3


def total_balance(conn: sqlite3.Connection) -> float:
    """Sum of all transaction amounts (positive = income, negative = expense)."""
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions").fetchone()
    return round(row[0], 2)


def total_expenses(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE amount < 0"
    ).fetchone()
    return round(abs(row[0]), 2)


def total_income(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE amount > 0"
    ).fetchone()
    return round(row[0], 2)


def by_category(conn: sqlite3.Connection) -> list[dict]:
    """Total spent per category (expenses only), sorted descending."""
    rows = conn.execute(
        """
        SELECT category,
               ROUND(SUM(amount), 2)       AS total,
               COUNT(*)                    AS count
        FROM   transactions
        WHERE  amount < 0
        GROUP  BY category
        ORDER  BY total ASC
        """
    ).fetchall()
    return [
        {"category": r["category"], "total": abs(r["total"]), "count": r["count"]}
        for r in rows
    ]


def by_month(conn: sqlite3.Connection) -> list[dict]:
    """Monthly income, expenses and net balance, sorted chronologically."""
    rows = conn.execute(
        """
        SELECT SUBSTR(date, 1, 7)               AS month,
               ROUND(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 2) AS income,
               ROUND(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 2) AS expenses,
               ROUND(SUM(amount), 2)            AS net
        FROM   transactions
        GROUP  BY month
        ORDER  BY month
        """
    ).fetchall()
    return [dict(r) for r in rows]


def top_expenses(conn: sqlite3.Connection, n: int = 10) -> list[dict]:
    """The N largest individual expenses."""
    rows = conn.execute(
        """
        SELECT date, description, amount, category
        FROM   transactions
        WHERE  amount < 0
        ORDER  BY amount ASC
        LIMIT  ?
        """,
        (n,),
    ).fetchall()
    return [
        {
            "date": r["date"],
            "description": r["description"],
            "amount": abs(r["amount"]),
            "category": r["category"],
        }
        for r in rows
    ]


def summary(conn: sqlite3.Connection) -> dict:
    """Single dict with all key metrics for the report."""
    return {
        "balance": total_balance(conn),
        "total_income": total_income(conn),
        "total_expenses": total_expenses(conn),
        "by_category": by_category(conn),
        "by_month": by_month(conn),
        "top_expenses": top_expenses(conn),
    }
