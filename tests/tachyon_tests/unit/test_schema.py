"""Unit tests for Neo4j schema definitions."""

import unittest


class TestSchemaDefinitions(unittest.TestCase):
    """Tests for schema module constants."""

    def test_uniqueness_constraints_list(self):
        """Test that uniqueness constraints are properly defined."""
        from tachyon.db.schema import UNIQUENESS_CONSTRAINTS

        self.assertIsInstance(UNIQUENESS_CONSTRAINTS, list)
        self.assertGreater(len(UNIQUENESS_CONSTRAINTS), 0)

        # Should have constraints for core entities
        all_constraints = " ".join(UNIQUENESS_CONSTRAINTS)
        self.assertIn("ResourceProvider", all_constraints)
        self.assertIn("Consumer", all_constraints)
        self.assertIn("Trait", all_constraints)
        self.assertIn("ResourceClass", all_constraints)

    def test_existence_constraints_list(self):
        """Test that existence constraints list is defined.

        Note: Property existence constraints require Neo4j Enterprise Edition.
        In Community Edition, we rely on application logic to enforce these.
        """
        from tachyon.db.schema import EXISTENCE_CONSTRAINTS

        self.assertIsInstance(EXISTENCE_CONSTRAINTS, list)
        # Currently empty due to Neo4j Community Edition limitation

    def test_indexes_list(self):
        """Test that indexes are properly defined."""
        from tachyon.db.schema import INDEXES

        self.assertIsInstance(INDEXES, list)
        self.assertGreater(len(INDEXES), 0)

        # All indexes should start with CREATE INDEX
        for idx in INDEXES:
            self.assertTrue(idx.strip().startswith("CREATE INDEX"))

    def test_schema_statements_combines_all(self):
        """Test that SCHEMA_STATEMENTS combines all schema definitions."""
        from tachyon.db.schema import (
            EXISTENCE_CONSTRAINTS,
            INDEXES,
            SCHEMA_STATEMENTS,
            UNIQUENESS_CONSTRAINTS,
        )

        expected_count = (
            len(UNIQUENESS_CONSTRAINTS) + len(EXISTENCE_CONSTRAINTS) + len(INDEXES)
        )
        self.assertEqual(len(SCHEMA_STATEMENTS), expected_count)

    def test_schema_uses_if_not_exists(self):
        """Test that all schema statements use IF NOT EXISTS for idempotency."""
        from tachyon.db.schema import SCHEMA_STATEMENTS

        for statement in SCHEMA_STATEMENTS:
            self.assertIn(
                "IF NOT EXISTS",
                statement,
                f"Statement missing IF NOT EXISTS: {statement[:50]}...",
            )

    def test_apply_schema_function_exists(self):
        """Test that apply_schema function is defined."""
        from tachyon.db.schema import apply_schema

        self.assertTrue(callable(apply_schema))


if __name__ == "__main__":
    unittest.main()
