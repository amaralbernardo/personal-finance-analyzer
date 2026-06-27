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
    return list(_load_rules(rules_path).keys()) + ["Outros"]


def categorize(description: str, rules: dict[str, list[str]]) -> str:
    desc_lower = description.lower()
    for category, keywords in rules.items():
        for kw in keywords:
            if kw.lower() in desc_lower:
                return category
    return "Outros"


def categorize_all(conn: sqlite3.Connection, space: str = None,
                   rules_path: Path = RULES_PATH,
                   mappings_path: Path = MAPPINGS_PATH) -> int:
    rules = _load_rules(rules_path)
    mappings = _load_mappings(mappings_path)

    if space is not None:
        rows = conn.execute(
            "SELECT id, description FROM transactions WHERE verified = 0 AND space = ?", (space,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, description FROM transactions WHERE verified = 0"
        ).fetchall()

    updated = 0
    for row in rows:
        desc = row["description"]
        if desc in mappings:
            if space is not None:
                conn.execute(
                    "UPDATE transactions SET category = ?, verified = 1 WHERE id = ? AND space = ?",
                    (mappings[desc], row["id"], space),
                )
            else:
                conn.execute(
                    "UPDATE transactions SET category = ?, verified = 1 WHERE id = ?",
                    (mappings[desc], row["id"]),
                )
            updated += 1
        else:
            cat = categorize(desc, rules)
            if cat != "Outros":
                if space is not None:
                    conn.execute(
                        "UPDATE transactions SET category = ? WHERE id = ? AND space = ?",
                        (cat, row["id"], space),
                    )
                else:
                    conn.execute(
                        "UPDATE transactions SET category = ? WHERE id = ?",
                        (cat, row["id"]),
                    )
                updated += 1

    conn.commit()
    return updated


def recategorize_all(conn: sqlite3.Connection, space: str = None,
                     rules_path: Path = RULES_PATH,
                     mappings_path: Path = MAPPINGS_PATH) -> int:
    rules = _load_rules(rules_path)
    mappings = _load_mappings(mappings_path)

    if space is not None:
        rows = conn.execute(
            "SELECT id, description FROM transactions WHERE space = ?", (space,)
        ).fetchall()
    else:
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
