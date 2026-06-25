"""Keyword-based categorization engine with user mapping support."""
import json
import sqlite3
from pathlib import Path

RULES_PATH = Path(__file__).parent / "rules.json"
MAPPINGS_PATH = Path(__file__).parents[2] / "data" / "user_mappings.json"


def _load_rules(rules_path: Path = RULES_PATH) -> dict[str, list[str]]:
    with open(rules_path, encoding="utf-8") as f:
        return json.load(f)


def _load_mappings(mappings_path: Path = MAPPINGS_PATH) -> dict[str, str]:
    if not mappings_path.exists():
        return {}
    with open(mappings_path, encoding="utf-8") as f:
        return json.load(f)


def load_categories(rules_path: Path = RULES_PATH) -> list[str]:
    """Return list of category names from rules.json, plus 'Outros'."""
    return list(_load_rules(rules_path).keys()) + ["Outros"]


def categorize(description: str, rules: dict[str, list[str]]) -> str:
    """Return the first matching category, or 'Outros' if none match."""
    desc_lower = description.lower()
    for category, keywords in rules.items():
        for kw in keywords:
            if kw.lower() in desc_lower:
                return category
    return "Outros"


def categorize_all(conn: sqlite3.Connection, rules_path: Path = RULES_PATH, mappings_path: Path = MAPPINGS_PATH) -> int:
    """
    Apply mappings (exact match) then rules (keywords) to all unverified transactions.
    Transactions matched via user_mappings are marked verified=1.
    Returns number of rows updated.
    """
    rules = _load_rules(rules_path)
    mappings = _load_mappings(mappings_path)
    rows = conn.execute(
        "SELECT id, description FROM transactions WHERE verified = 0"
    ).fetchall()

    updated = 0
    for row in rows:
        desc = row["description"]
        if desc in mappings:
            conn.execute(
                "UPDATE transactions SET category = ?, verified = 1 WHERE id = ?",
                (mappings[desc], row["id"]),
            )
            updated += 1
        else:
            cat = categorize(desc, rules)
            if cat != "Outros":
                conn.execute(
                    "UPDATE transactions SET category = ? WHERE id = ?",
                    (cat, row["id"]),
                )
                updated += 1

    conn.commit()
    return updated


def recategorize_all(conn: sqlite3.Connection, rules_path: Path = RULES_PATH, mappings_path: Path = MAPPINGS_PATH) -> int:
    """Re-apply rules to ALL transactions, preserving user-verified mappings."""
    rules = _load_rules(rules_path)
    mappings = _load_mappings(mappings_path)
    rows = conn.execute("SELECT id, description FROM transactions").fetchall()

    for row in rows:
        desc = row["description"]
        if desc in mappings:
            conn.execute(
                "UPDATE transactions SET category = ?, verified = 1 WHERE id = ?",
                (mappings[desc], row["id"]),
            )
        else:
            cat = categorize(desc, rules)
            conn.execute(
                "UPDATE transactions SET category = ?, verified = 0 WHERE id = ?",
                (cat, row["id"]),
            )

    conn.commit()
    return len(rows)
