# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Tachyon schema module."""

from unittest import mock

from oslotest import base

from tachyon.db import schema


class TestSchemaConstants(base.BaseTestCase):
    """Tests for schema constants."""

    def test_uniqueness_constraints_non_empty(self):
        """Test UNIQUENESS_CONSTRAINTS is not empty."""
        self.assertGreater(len(schema.UNIQUENESS_CONSTRAINTS), 0)

    def test_uniqueness_constraints_contain_if_not_exists(self):
        """Test all uniqueness constraints use IF NOT EXISTS."""
        for constraint in schema.UNIQUENESS_CONSTRAINTS:
            self.assertIn("IF NOT EXISTS", constraint)

    def test_indexes_non_empty(self):
        """Test INDEXES is not empty."""
        self.assertGreater(len(schema.INDEXES), 0)

    def test_indexes_contain_if_not_exists(self):
        """Test all indexes use IF NOT EXISTS."""
        for index in schema.INDEXES:
            self.assertIn("IF NOT EXISTS", index)

    def test_schema_statements_combined(self):
        """Test SCHEMA_STATEMENTS contains all constraints and indexes."""
        expected_count = (
            len(schema.UNIQUENESS_CONSTRAINTS)
            + len(schema.EXISTENCE_CONSTRAINTS)
            + len(schema.INDEXES)
        )
        self.assertEqual(len(schema.SCHEMA_STATEMENTS), expected_count)

    def test_resource_provider_uuid_constraint(self):
        """Test ResourceProvider UUID uniqueness constraint exists."""
        has_rp_uuid_constraint = any(
            "ResourceProvider" in c and "uuid" in c
            for c in schema.UNIQUENESS_CONSTRAINTS
        )
        self.assertTrue(has_rp_uuid_constraint)

    def test_consumer_uuid_constraint(self):
        """Test Consumer UUID uniqueness constraint exists."""
        has_consumer_constraint = any(
            "Consumer" in c and "uuid" in c for c in schema.UNIQUENESS_CONSTRAINTS
        )
        self.assertTrue(has_consumer_constraint)


class TestApplySchema(base.BaseTestCase):
    """Tests for apply_schema function."""

    def test_apply_schema_runs_all_statements(self):
        """Test apply_schema runs all schema statements."""
        mock_session = mock.MagicMock()

        schema.apply_schema(mock_session)

        self.assertEqual(mock_session.run.call_count, len(schema.SCHEMA_STATEMENTS))

    def test_apply_schema_calls_with_statements(self):
        """Test apply_schema passes correct statements."""
        mock_session = mock.MagicMock()

        schema.apply_schema(mock_session)

        calls = mock_session.run.call_args_list
        for i, call in enumerate(calls):
            args, kwargs = call
            self.assertEqual(args[0], schema.SCHEMA_STATEMENTS[i])
