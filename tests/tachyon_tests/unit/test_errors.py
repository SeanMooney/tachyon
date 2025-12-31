# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Tachyon errors module."""

from unittest import mock

from oslotest import base

from tachyon.api import app, errors


class TestTachyonException(base.BaseTestCase):
    """Tests for TachyonException base class."""

    def test_basic_exception_with_reason(self):
        """Test creating exception with simple reason string."""
        exc = errors.TachyonException("Test error message")
        self.assertEqual(exc.detail, "Test error message")
        self.assertEqual(exc.status_code, 500)
        self.assertEqual(exc.title, "Internal Server Error")
        self.assertIsNone(exc.code)

    def test_exception_with_kwargs(self):
        """Test creating exception with keyword arguments."""
        exc = errors.TachyonException(reason="Custom reason")
        self.assertEqual(exc.detail, "Custom reason")
        self.assertIn("reason", exc.kwargs)

    def test_exception_with_code(self):
        """Test that code can be passed via kwargs."""
        exc = errors.TachyonException("Test", code="test.code")
        self.assertEqual(exc.code, "test.code")

    def test_exception_str_representation(self):
        """Test that str() returns the detail message."""
        exc = errors.TachyonException("Test error")
        self.assertEqual(str(exc), "Test error")


class TestNotFound(base.BaseTestCase):
    """Tests for NotFound exception."""

    def test_not_found_with_reason(self):
        """Test NotFound with simple reason."""
        exc = errors.NotFound("Resource not found")
        self.assertEqual(exc.detail, "Resource not found")
        self.assertEqual(exc.status_code, 404)
        self.assertEqual(exc.title, "Not Found")

    def test_not_found_with_kwargs(self):
        """Test NotFound with resource_type and uuid."""
        exc = errors.NotFound(resource_type="resource provider", uuid="abc-123")
        self.assertIn("resource provider", exc.detail)
        self.assertIn("abc-123", exc.detail)

    def test_not_found_inherits_status_code(self):
        """Test NotFound has correct status code."""
        exc = errors.NotFound("test")
        self.assertEqual(exc.status_code, 404)


class TestConflict(base.BaseTestCase):
    """Tests for Conflict exception."""

    def test_conflict_with_reason(self):
        """Test Conflict with simple reason."""
        exc = errors.Conflict("Generation mismatch")
        self.assertEqual(exc.detail, "Generation mismatch")
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(exc.title, "Conflict")

    def test_conflict_with_code(self):
        """Test Conflict with error code."""
        exc = errors.Conflict("test conflict", code="placement.concurrent_update")
        self.assertEqual(exc.code, "placement.concurrent_update")


class TestBadRequest(base.BaseTestCase):
    """Tests for BadRequest exception."""

    def test_bad_request_with_reason(self):
        """Test BadRequest with simple reason."""
        exc = errors.BadRequest("'name' is a required property")
        self.assertEqual(exc.detail, "'name' is a required property")
        self.assertEqual(exc.status_code, 400)
        self.assertEqual(exc.title, "Bad Request")


class TestResourceProviderGenerationConflict(base.BaseTestCase):
    """Tests for ResourceProviderGenerationConflict exception."""

    def test_generation_conflict_defaults(self):
        """Test ResourceProviderGenerationConflict has correct defaults."""
        exc = errors.ResourceProviderGenerationConflict()
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(exc.title, "Conflict")
        self.assertEqual(exc.code, "placement.concurrent_update")

    def test_generation_conflict_detail(self):
        """Test ResourceProviderGenerationConflict message."""
        exc = errors.ResourceProviderGenerationConflict()
        self.assertIn("generation conflict", exc.detail)


class TestConsumerGenerationConflict(base.BaseTestCase):
    """Tests for ConsumerGenerationConflict exception."""

    def test_consumer_conflict_with_kwargs(self):
        """Test ConsumerGenerationConflict with format args."""
        exc = errors.ConsumerGenerationConflict(uuid="consumer-123", expected=0, got=1)
        self.assertIn("consumer-123", exc.detail)
        self.assertEqual(exc.status_code, 409)


class TestInventoryInUse(base.BaseTestCase):
    """Tests for InventoryInUse exception."""

    def test_inventory_in_use_with_kwargs(self):
        """Test InventoryInUse with format args."""
        exc = errors.InventoryInUse(resource_class="VCPU", allocation_count=5)
        self.assertIn("VCPU", exc.detail)
        self.assertIn("5", exc.detail)
        self.assertEqual(exc.status_code, 409)


class TestResourceProviderInUse(base.BaseTestCase):
    """Tests for ResourceProviderInUse exception."""

    def test_rp_in_use_with_kwargs(self):
        """Test ResourceProviderInUse with format args."""
        exc = errors.ResourceProviderInUse(uuid="rp-123", reason="has children")
        self.assertIn("rp-123", exc.detail)
        self.assertIn("has children", exc.detail)


class TestDuplicateName(base.BaseTestCase):
    """Tests for DuplicateName exception."""

    def test_duplicate_name_with_kwargs(self):
        """Test DuplicateName with format args."""
        exc = errors.DuplicateName(resource_type="resource provider", name="test-rp")
        self.assertIn("test-rp", exc.detail)
        self.assertIn("already exists", exc.detail)
        self.assertEqual(exc.code, "placement.duplicate_name")


class TestDuplicateUUID(base.BaseTestCase):
    """Tests for DuplicateUUID exception."""

    def test_duplicate_uuid_with_kwargs(self):
        """Test DuplicateUUID with format args."""
        exc = errors.DuplicateUUID(resource_type="resource provider", uuid="abc-123")
        self.assertIn("abc-123", exc.detail)
        self.assertIn("already exists", exc.detail)


class TestExceptionToResponse(base.BaseTestCase):
    """Tests for exception to_response method."""

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_to_response_format(self, mock_init_neo4j):
        """Test that to_response returns Placement-compatible format."""
        flask_app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

        with flask_app.app_context():
            exc = errors.NotFound("Resource xyz not found")
            response, status = exc.to_response()

            self.assertEqual(status, 404)
            data = response.get_json()
            self.assertIn("errors", data)
            self.assertEqual(len(data["errors"]), 1)
            self.assertEqual(data["errors"][0]["status"], 404)
            self.assertEqual(data["errors"][0]["title"], "Not Found")
            self.assertEqual(data["errors"][0]["detail"], "Resource xyz not found")

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_to_response_with_code(self, mock_init_neo4j):
        """Test that error code is included in response."""
        flask_app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

        with flask_app.app_context():
            exc = errors.ResourceProviderGenerationConflict()
            response, status = exc.to_response()

            data = response.get_json()
            self.assertIn("code", data["errors"][0])
            self.assertEqual(data["errors"][0]["code"], "placement.concurrent_update")


class TestErrorResponseHelper(base.BaseTestCase):
    """Tests for error_response helper function."""

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def test_error_response_format(self, mock_init_neo4j):
        """Test error_response helper creates correct format."""
        flask_app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

        with flask_app.app_context():
            response, status = errors.error_response(
                422, "Unprocessable", "Cannot process request"
            )

            self.assertEqual(status, 422)
            data = response.get_json()
            self.assertEqual(data["errors"][0]["status"], 422)
            self.assertEqual(data["errors"][0]["title"], "Unprocessable")
            self.assertEqual(data["errors"][0]["detail"], "Cannot process request")


class TestBackwardCompatibility(base.BaseTestCase):
    """Tests for backward compatibility with old API."""

    def test_api_error_alias(self):
        """Test that APIError is an alias for TachyonException."""
        self.assertIs(errors.APIError, errors.TachyonException)

    def test_old_style_exception_creation(self):
        """Test old-style exception creation still works."""
        # Old style: errors.BadRequest("message")
        exc = errors.BadRequest("Old style message")
        self.assertEqual(exc.detail, "Old style message")

        # Old style with code: errors.Conflict("msg", code="...")
        exc2 = errors.Conflict("Conflict message", code="test.code")
        self.assertEqual(exc2.detail, "Conflict message")
        self.assertEqual(exc2.code, "test.code")
