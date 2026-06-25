from app.categorize.engine import categorize, categorize_all, recategorize_all

RULES = {
    "Alimentação": ["continente", "pingo doce", "lidl"],
    "Transportes": ["uber", "galp"],
    "Lazer":       ["netflix"],
}


class TestCategorize:
    def test_exact_match(self):
        assert categorize("CONTINENTE MODELO", RULES) == "Alimentação"

    def test_case_insensitive(self):
        assert categorize("uber trip", RULES) == "Transportes"

    def test_partial_match(self):
        assert categorize("PINGO DOCE CASCAIS", RULES) == "Alimentação"

    def test_no_match_returns_outros(self):
        assert categorize("TRANSFERENCIA BANCARIA", RULES) == "Outros"

    def test_first_rule_wins(self):
        # "galp" is in Transportes; should not bleed into other categories
        assert categorize("GALP COMBUSTIVEL", RULES) == "Transportes"


class TestCategorizeAll:
    def test_only_updates_outros(self, db):
        # Pre-set one row to a known category
        db.execute("UPDATE transactions SET category='Alimentação' WHERE description='CONTINENTE MODELO'")
        db.commit()

        updated = categorize_all(db)
        # Continente was already categorized, so it should not be re-touched
        row = db.execute(
            "SELECT category FROM transactions WHERE description='CONTINENTE MODELO'"
        ).fetchone()
        assert row["category"] == "Alimentação"
        # Others that matched should now be categorized
        assert updated > 0

    def test_returns_count(self, db):
        updated = categorize_all(db)
        assert isinstance(updated, int)
        assert updated >= 0


class TestRecategorizeAll:
    def test_updates_all_rows(self, db):
        # Force everything to "Outros" first
        db.execute("UPDATE transactions SET category='Outros'")
        db.commit()

        count = recategorize_all(db)
        assert count == 8  # total rows in fixture

    def test_galp_becomes_transportes(self, db):
        recategorize_all(db)
        row = db.execute(
            "SELECT category FROM transactions WHERE description='GALP COMBUSTIVEL'"
        ).fetchone()
        assert row["category"] == "Transportes"
