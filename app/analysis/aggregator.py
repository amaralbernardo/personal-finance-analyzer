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


def patrimony_balances(conn: sqlite3.Connection, space: str = 'joint') -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT p.category, p.label,
               p.amount AS initial_amount,
               p.reference_date,
               p.amount + COALESCE(SUM(t.amount), 0) AS current_value
        FROM patrimony p
        LEFT JOIN transactions t
               ON t.patrimony_label = p.label
              AND t.space = p.space
              AND t.date >= p.reference_date
        WHERE p.space = ?
        GROUP BY p.id
        ORDER BY p.category
    """, (space,)).fetchall()]


def patrimony_evolution(conn: sqlite3.Connection, space: str = 'joint') -> dict:
    patrimonies = conn.execute(
        "SELECT label, amount, reference_date FROM patrimony WHERE space = ?", (space,)
    ).fetchall()
    if not patrimonies:
        return {}

    account_data = {}
    all_months: set = set()

    for p in patrimonies:
        lbl = p["label"]
        ref_month = p["reference_date"][:7]
        all_months.add(ref_month)

        monthly = conn.execute("""
            SELECT SUBSTR(date, 1, 7) AS month, ROUND(SUM(amount), 2) AS net
            FROM transactions
            WHERE patrimony_label = ? AND space = ? AND date >= ?
            GROUP BY month ORDER BY month
        """, (lbl, space, p["reference_date"])).fetchall()

        by_month_map: dict = {}
        running = p["amount"]
        by_month_map[ref_month] = running
        for m in monthly:
            ms = m["month"]
            all_months.add(ms)
            running = round(running + m["net"], 2)
            by_month_map[ms] = running

        account_data[lbl] = {"by_month": by_month_map, "ref_month": ref_month, "initial": p["amount"]}

    sorted_months = sorted(all_months)
    result = {}
    for lbl, info in account_data.items():
        months, values = [], []
        last = info["initial"]
        for month in sorted_months:
            if month < info["ref_month"]:
                continue
            last = info["by_month"].get(month, last)
            months.append(month)
            values.append(last)
        result[lbl] = {"months": months, "values": values}

    return result


def monthly_by_account(conn: sqlite3.Connection, space: str = 'joint') -> dict:
    rows = conn.execute("""
        SELECT SUBSTR(date, 1, 7) AS month,
               patrimony_label AS account,
               ROUND(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 2) AS income,
               ROUND(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 2) AS expenses
        FROM transactions
        WHERE space = ? AND patrimony_label IS NOT NULL
        GROUP BY month, account ORDER BY month
    """, (space,)).fetchall()

    result: dict = {}
    for r in rows:
        acc = r["account"]
        if acc not in result:
            result[acc] = {"months": [], "income": [], "expenses": []}
        result[acc]["months"].append(r["month"])
        result[acc]["income"].append(r["income"])
        result[acc]["expenses"].append(r["expenses"])
    return result


def transactions_by_account(conn: sqlite3.Connection, space: str = 'joint') -> dict:
    rows = conn.execute("""
        SELECT date, description, notes, amount, category, patrimony_label
        FROM transactions WHERE space = ? ORDER BY date DESC
    """, (space,)).fetchall()

    result: dict = {}
    for r in rows:
        acc = r["patrimony_label"] or "__none__"
        if acc not in result:
            result[acc] = []
        result[acc].append(dict(r))
    return result


def transactions_all(conn: sqlite3.Connection, space: str = 'joint') -> list[dict]:
    return [dict(r) for r in conn.execute("""
        SELECT date, description, notes, amount, category, patrimony_label
        FROM transactions WHERE space = ? ORDER BY date DESC
    """, (space,)).fetchall()]
