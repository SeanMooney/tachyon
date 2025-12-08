"""Unit tests for the Tachyon Flask application factory."""

import unittest
from unittest import mock

from tachyon.api import create_app
from tachyon.api.errors import (
    APIError,
    BadRequest,
    Conflict,
    ConsumerGenerationConflict,
    InventoryInUse,
    NotFound,
    ResourceProviderGenerationConflict,
    error_response,
)


class TestCreateApp(unittest.TestCase):
    """Tests for the create_app factory function."""

    @mock.patch("tachyon.api.app.init_driver")
    def test_create_app_defaults(self, mock_init_driver):
        """Test app creation with default configuration."""
        mock_driver = mock.MagicMock()
        mock_init_driver.return_value = mock_driver

        app = create_app({"TESTING": True})

        self.assertEqual(app.config["AUTH_STRATEGY"], "noauth2")
        self.assertEqual(app.config["MAX_LIMIT"], 1000)
        self.assertTrue(app.config["TESTING"])

    @mock.patch("tachyon.api.app.init_driver")
    def test_create_app_custom_config(self, mock_init_driver):
        """Test app creation with custom configuration."""
        mock_driver = mock.MagicMock()
        mock_init_driver.return_value = mock_driver

        app = create_app(
            {
                "TESTING": True,
                "AUTH_STRATEGY": "keystone",
                "MAX_LIMIT": 500,
            }
        )

        self.assertEqual(app.config["AUTH_STRATEGY"], "keystone")
        self.assertEqual(app.config["MAX_LIMIT"], 500)

    @mock.patch("tachyon.api.app.init_driver")
    def test_blueprints_registered(self, mock_init_driver):
        """Test that all blueprints are registered."""
        mock_driver = mock.MagicMock()
        mock_init_driver.return_value = mock_driver

        app = create_app({"TESTING": True})

        # Check that expected blueprints are registered
        blueprint_names = list(app.blueprints.keys())
        self.assertIn("resource_providers", blueprint_names)
        self.assertIn("inventories", blueprint_names)
        self.assertIn("traits", blueprint_names)
        self.assertIn("resource_classes", blueprint_names)
        self.assertIn("allocations", blueprint_names)
        self.assertIn("usages", blueprint_names)


class TestAPIErrors(unittest.TestCase):
    """Tests for API error handling."""

    def test_api_error_base(self):
        """Test base APIError class."""
        error = APIError("Test error message")
        self.assertEqual(error.detail, "Test error message")
        self.assertEqual(error.status_code, 500)
        self.assertEqual(error.title, "Internal Server Error")

    def test_not_found_error(self):
        """Test NotFound error."""
        error = NotFound("Resource not found")
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.title, "Not Found")
        self.assertEqual(error.detail, "Resource not found")

    def test_conflict_error(self):
        """Test Conflict error."""
        error = Conflict("Conflict occurred")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Conflict")

    def test_bad_request_error(self):
        """Test BadRequest error."""
        error = BadRequest("Invalid input")
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.title, "Bad Request")

    def test_resource_provider_generation_conflict(self):
        """Test ResourceProviderGenerationConflict error."""
        error = ResourceProviderGenerationConflict("Generation mismatch")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Resource Provider Generation Conflict")

    def test_consumer_generation_conflict(self):
        """Test ConsumerGenerationConflict error."""
        error = ConsumerGenerationConflict("Consumer generation mismatch")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Consumer Generation Conflict")

    def test_inventory_in_use_error(self):
        """Test InventoryInUse error."""
        error = InventoryInUse("Inventory has allocations")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Inventory In Use")

    @mock.patch("tachyon.api.app.init_driver")
    def test_error_to_response(self, mock_init_driver):
        """Test error serialization to response."""
        mock_driver = mock.MagicMock()
        mock_init_driver.return_value = mock_driver

        app = create_app({"TESTING": True})

        with app.app_context():
            error = NotFound("Resource xyz not found")
            response, status = error.to_response()

            self.assertEqual(status, 404)
            data = response.get_json()
            self.assertIn("errors", data)
            self.assertEqual(len(data["errors"]), 1)
            self.assertEqual(data["errors"][0]["status"], 404)
            self.assertEqual(data["errors"][0]["title"], "Not Found")
            self.assertEqual(data["errors"][0]["detail"], "Resource xyz not found")

    @mock.patch("tachyon.api.app.init_driver")
    def test_error_response_helper(self, mock_init_driver):
        """Test error_response helper function."""
        mock_driver = mock.MagicMock()
        mock_init_driver.return_value = mock_driver

        app = create_app({"TESTING": True})

        with app.app_context():
            response, status = error_response(422, "Unprocessable", "Cannot process")

            self.assertEqual(status, 422)
            data = response.get_json()
            self.assertEqual(data["errors"][0]["status"], 422)
            self.assertEqual(data["errors"][0]["title"], "Unprocessable")
            self.assertEqual(data["errors"][0]["detail"], "Cannot process")


class TestSchemaHelpers(unittest.TestCase):
    """Tests for database schema helpers."""

    def test_schema_statements_defined(self):
        """Test that schema statements are properly defined."""
        from tachyon.db.schema import SCHEMA_STATEMENTS

        self.assertIsInstance(SCHEMA_STATEMENTS, list)
        self.assertGreater(len(SCHEMA_STATEMENTS), 0)

        # Check that all statements are strings
        for statement in SCHEMA_STATEMENTS:
            self.assertIsInstance(statement, str)
            # Statements should be valid Cypher
            self.assertTrue(
                statement.startswith("CREATE CONSTRAINT")
                or statement.startswith("CREATE INDEX")
            )

    def test_uniqueness_constraints_present(self):
        """Test that uniqueness constraints are defined."""
        from tachyon.db.schema import UNIQUENESS_CONSTRAINTS

        constraint_names = " ".join(UNIQUENESS_CONSTRAINTS).lower()

        # Check for key constraints (labels use PascalCase without underscores)
        self.assertIn("resourceprovider", constraint_names)
        self.assertIn("consumer", constraint_names)
        self.assertIn("trait", constraint_names)
        self.assertIn("resourceclass", constraint_names)


if __name__ == "__main__":
    unittest.main()
