# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Tachyon Flask application factory."""

from unittest import mock

from oslotest import base

from tachyon.api import app
from tachyon.api import errors
from tachyon.db import schema


class TestCreateApp(base.BaseTestCase):
    """Tests for the create_app factory function."""

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_create_app_defaults(self, mock_init_neo4j):
        """Test app creation with default configuration."""
        flask_app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

        self.assertEqual(flask_app.config["AUTH_STRATEGY"], "noauth2")
        self.assertEqual(flask_app.config["MAX_LIMIT"], 1000)
        self.assertTrue(flask_app.config["TESTING"])

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_create_app_custom_config(self, mock_init_neo4j):
        """Test app creation with custom configuration."""
        flask_app = app.create_app(
            {
                "TESTING": True,
                "SKIP_DB_INIT": True,
                "AUTH_STRATEGY": "keystone",
                "MAX_LIMIT": 500,
            }
        )

        self.assertEqual(flask_app.config["AUTH_STRATEGY"], "keystone")
        self.assertEqual(flask_app.config["MAX_LIMIT"], 500)

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_blueprints_registered(self, mock_init_neo4j):
        """Test that all blueprints are registered."""
        flask_app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

        # Check that expected blueprints are registered
        blueprint_names = list(flask_app.blueprints.keys())
        self.assertIn("resource_providers", blueprint_names)
        self.assertIn("inventories", blueprint_names)
        self.assertIn("traits", blueprint_names)
        self.assertIn("resource_classes", blueprint_names)
        self.assertIn("allocations", blueprint_names)
        self.assertIn("usages", blueprint_names)


class TestAPIErrors(base.BaseTestCase):
    """Tests for API error handling."""

    def test_api_error_base(self):
        """Test base APIError class."""
        error = errors.APIError("Test error message")
        self.assertEqual(error.detail, "Test error message")
        self.assertEqual(error.status_code, 500)
        self.assertEqual(error.title, "Internal Server Error")

    def test_not_found_error(self):
        """Test NotFound error."""
        error = errors.NotFound("Resource not found")
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.title, "Not Found")
        self.assertEqual(error.detail, "Resource not found")

    def test_conflict_error(self):
        """Test Conflict error."""
        error = errors.Conflict("Conflict occurred")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Conflict")

    def test_bad_request_error(self):
        """Test BadRequest error."""
        error = errors.BadRequest("Invalid input")
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.title, "Bad Request")

    def test_resource_provider_generation_conflict(self):
        """Test ResourceProviderGenerationConflict error."""
        error = errors.ResourceProviderGenerationConflict("Generation mismatch")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Conflict")

    def test_consumer_generation_conflict(self):
        """Test ConsumerGenerationConflict error."""
        error = errors.ConsumerGenerationConflict("Consumer generation mismatch")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Consumer Generation Conflict")

    def test_inventory_in_use_error(self):
        """Test InventoryInUse error."""
        error = errors.InventoryInUse("Inventory has allocations")
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.title, "Inventory In Use")

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_error_to_response(self, mock_init_neo4j):
        """Test error serialization to response."""
        flask_app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

        with flask_app.app_context():
            error = errors.NotFound("Resource xyz not found")
            response, status = error.to_response()

            self.assertEqual(status, 404)
            data = response.get_json()
            self.assertIn("errors", data)
            self.assertEqual(len(data["errors"]), 1)
            self.assertEqual(data["errors"][0]["status"], 404)
            self.assertEqual(data["errors"][0]["title"], "Not Found")
            self.assertEqual(data["errors"][0]["detail"], "Resource xyz not found")

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_error_response_helper(self, mock_init_neo4j):
        """Test error_response helper function."""
        flask_app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

        with flask_app.app_context():
            response, status = errors.error_response(
                422, "Unprocessable", "Cannot process"
            )

            self.assertEqual(status, 422)
            data = response.get_json()
            self.assertEqual(data["errors"][0]["status"], 422)
            self.assertEqual(data["errors"][0]["title"], "Unprocessable")
            self.assertEqual(data["errors"][0]["detail"], "Cannot process")


class TestSchemaHelpers(base.BaseTestCase):
    """Tests for database schema helpers."""

    def test_uniqueness_constraints_defined(self):
        """Test that uniqueness constraints are properly defined."""
        self.assertIsInstance(schema.UNIQUENESS_CONSTRAINTS, list)
        self.assertGreater(len(schema.UNIQUENESS_CONSTRAINTS), 0)

        # Check that all statements are strings
        for statement in schema.UNIQUENESS_CONSTRAINTS:
            self.assertIsInstance(statement, str)
            # Statements should be valid Cypher
            self.assertTrue(statement.startswith("CREATE CONSTRAINT"))

    def test_uniqueness_constraints_present(self):
        """Test that uniqueness constraints are defined."""
        constraint_names = " ".join(schema.UNIQUENESS_CONSTRAINTS).lower()

        # Check for key constraints (labels use PascalCase without underscores)
        self.assertIn("resourceprovider", constraint_names)
        self.assertIn("consumer", constraint_names)
        self.assertIn("trait", constraint_names)
        self.assertIn("resourceclass", constraint_names)
