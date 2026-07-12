"""Keyword-based categorization engine with user mapping support."""
import json
import sqlite3
from pathlib import Path

RULES_PATH = Path(__file__).parent / "rules.json"
MAPPINGS_PATH = Path(__file__).parents[2] / "data" / "user_mappings.json"


def _load_rules(rules_path: Path = RULES_PATH) -> dict[str, list[str]]:
    with open(rules_path, encoding="utf-8") as f:
        return json.load(f)


def _load_mappings(mappings_path: Path = MAPPINGS_PATH, space: str = 'joint') -> dict[str, str]:
    if not mappings_path.exists():
        return {}
    with open(mappings_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(space, {})


def _save_mappings(mappings_path: Path, space: str, mappings: dict) -> None:
    data = {}
    if mappings_path.exists():
        with open(mappings_path, encoding="utf-8") as f:
            data = json.load(f)
    data[space] = mappings
    mappings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(mappings_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_categories(rules_path: Path = RULES_PATH) -> list[str]:
    return list(_load_rules(rules_path).keys()) + ["Outros"]


def categorize(description: str, rules: dict[str, list[str]]) -> str:
    desc_lower = description.lower()
    for category, keywords in rules.items():
        for kw in keywords:
            if kw.lower() in desc_lower:
                return category
    return "Outros"


def categorize_all(conn: sqlite3.Connection, space: str = 'joint',
                   rules_path: Path = RULES_PATH,
                   mappings_path: Path = MAPPINGS_PATH) -> int:
    rules = _load_rules(rules_path)
    mappings = _load_mappings(mappings_path, space)

    rows = conn.execute(
        "SELECT id, description FROM transactions WHERE verified = 0 AND space = ?", (space,)
    ).fetchall()

    updated = 0
    for row in rows:
        desc = row["description"]
        if desc in mappings:
            conn.execute(
                "UPDATE transactions SET category = ?, verified = 1 WHERE id = ? AND space = ?",
                (mappings[desc], row["id"], space),
            )
            updated += 1
        else:
            cat = categorize(desc, rules)
            if cat != "Outros":
                conn.execute(
                    "UPDATE transactions SET category = ? WHERE id = ? AND space = ?",
                    (cat, row["id"], space),
                )
                updated += 1

    conn.commit()
    return updated


def recategorize_all(conn: sqlite3.Connection, space: str = 'joint',
                     rules_path: Path = RULES_PATH,
                     mappings_path: Path = MAPPINGS_PATH) -> int:
    rules = _load_rules(rules_path)
    mappings = _load_mappings(mappings_path, space)

    rows = conn.execute(
        "SELECT id, description FROM transactions WHERE space = ?", (space,)
    ).fetchall()

    for row in rows:
        desc = row["description"]
        if desc in mappings:
            conn.execute(
                "UPDATE transactions SET category = ?, verified = 1 WHERE id = ? AND space = ?",
                (mappings[desc], row["id"], space),
            )
        else:
            cat = categorize(desc, rules)
            conn.execute(
                "UPDATE transactions SET category = ?, verified = 0 WHERE id = ? AND space = ?",
                (cat, row["id"], space),
            )

    conn.commit()
    return len(rows)
