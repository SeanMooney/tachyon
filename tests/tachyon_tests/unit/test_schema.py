# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Neo4j schema definitions."""

from oslotest import base

from tachyon.db import schema


class TestSchemaDefinitions(base.BaseTestCase):
    """Tests for schema module constants."""

    def test_uniqueness_constraints_list(self):
        """Test that uniqueness constraints are properly defined."""
        self.assertIsInstance(schema.UNIQUENESS_CONSTRAINTS, list)
        self.assertGreater(len(schema.UNIQUENESS_CONSTRAINTS), 0)

        # Should have constraints for core entities
        all_constraints = " ".join(schema.UNIQUENESS_CONSTRAINTS)
        self.assertIn("ResourceProvider", all_constraints)
        self.assertIn("Consumer", all_constraints)
        self.assertIn("Trait", all_constraints)
        self.assertIn("ResourceClass", all_constraints)

    def test_existence_constraints_list(self):
        """Test that existence constraints list is defined.

        Note: Property existence constraints require Neo4j Enterprise Edition.
        In Community Edition, we rely on application logic to enforce these.
        """
        self.assertIsInstance(schema.EXISTENCE_CONSTRAINTS, list)
        # Currently empty due to Neo4j Community Edition limitation

    def test_indexes_list(self):
        """Test that indexes are properly defined."""
        self.assertIsInstance(schema.INDEXES, list)
        self.assertGreater(len(schema.INDEXES), 0)

        # All indexes should start with CREATE INDEX
        for idx in schema.INDEXES:
            self.assertTrue(idx.strip().startswith("CREATE INDEX"))

    def test_schema_statements_combines_all(self):
        """Test that SCHEMA_STATEMENTS combines all schema definitions."""
        expected_count = (
            len(schema.UNIQUENESS_CONSTRAINTS)
            + len(schema.EXISTENCE_CONSTRAINTS)
            + len(schema.INDEXES)
        )
        self.assertEqual(len(schema.SCHEMA_STATEMENTS), expected_count)

    def test_schema_uses_if_not_exists(self):
        """Test that all schema statements use IF NOT EXISTS for idempotency."""
        for statement in schema.SCHEMA_STATEMENTS:
            self.assertIn(
                "IF NOT EXISTS",
                statement,
                "Statement missing IF NOT EXISTS: %s..." % statement[:50],
            )

    def test_apply_schema_function_exists(self):
        """Test that apply_schema function is defined."""
        self.assertTrue(callable(schema.apply_schema))
