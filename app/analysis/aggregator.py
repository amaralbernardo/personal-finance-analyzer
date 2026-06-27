"""Aggregation queries over the transactions table."""
import sqlite3


def total_balance(conn: sqlite3.Connection, space: str = 'joint') -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE space = ?", (space,)
    ).fetchone()
    return round(row[0], 2)


def total_expenses(conn: sqlite3.Connection, space: str = 'joint') -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE amount < 0 AND space = ?", (space,)
    ).fetchone()
    return round(abs(row[0]), 2)


def total_income(conn: sqlite3.Connection, space: str = 'joint') -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE amount > 0 AND space = ?", (space,)
    ).fetchone()
    return round(row[0], 2)


def by_category(conn: sqlite3.Connection, space: str = 'joint') -> list[dict]:
    rows = conn.execute(
        """
        SELECT category,
               ROUND(SUM(amount), 2)  AS total,
               COUNT(*)               AS count
        FROM   transactions
        WHERE  amount < 0 AND space = ?
        GROUP  BY category
        ORDER  BY total ASC
        """, (space,)
    ).fetchall()
    return [
        {"category": r["category"], "total": abs(r["total"]), "count": r["count"]}
        for r in rows
    ]


def by_month(conn: sqlite3.Connection, space: str = 'joint') -> list[dict]:
    rows = conn.execute(
        """
        SELECT SUBSTR(date, 1, 7)                                               AS month,
               ROUND(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 2)      AS income,
               ROUND(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 2) AS expenses,
               ROUND(SUM(amount), 2)                                            AS net
        FROM   transactions
        WHERE  space = ?
        GROUP  BY month
        ORDER  BY month
        """, (space,)
    ).fetchall()
    return [dict(r) for r in rows]


def top_expenses(conn: sqlite3.Connection, space: str = 'joint', n: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT date, description, amount, category
        FROM   transactions
        WHERE  amount < 0 AND space = ?
        ORDER  BY amount ASC
        LIMIT  ?
        """, (space, n)
    ).fetchall()
    return [
        {"date": r["date"], "description": r["description"],
         "amount": abs(r["amount"]), "category": r["category"]}
        for r in rows
    ]


def summary(conn: sqlite3.Connection, space: str = 'joint') -> dict:
    return {
        "balance":        total_balance(conn, space),
        "total_income":   total_income(conn, space),
        "total_expenses": total_expenses(conn, space),
        "by_category":    by_category(conn, space),
        "by_month":       by_month(conn, space),
        "top_expenses":   top_expenses(conn, space),
    }
