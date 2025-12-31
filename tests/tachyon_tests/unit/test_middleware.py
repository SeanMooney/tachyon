# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Tachyon middleware module."""

from unittest import mock

from oslotest import base

from tachyon.api import app, microversion


class TestMiddleware(base.BaseTestCase):
    """Tests for request middleware."""

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def setUp(self, mock_init_neo4j):
        """Set up test fixtures."""
        super().setUp()
        self.app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})
        self.client = self.app.test_client()

    def test_microversion_header_default(self):
        """Test default microversion when no header provided."""
        response = self.client.get("/", headers={"X-Auth-Token": "admin"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("OpenStack-API-Version", response.headers)
        self.assertIn("placement 1.0", response.headers["OpenStack-API-Version"])

    def test_microversion_header_specific(self):
        """Test microversion with specific version header."""
        response = self.client.get(
            "/",
            headers={
                "X-Auth-Token": "admin",
                "OpenStack-API-Version": "placement 1.15",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("placement 1.15", response.headers["OpenStack-API-Version"])

    def test_microversion_header_latest(self):
        """Test microversion with 'latest' returns max supported."""
        response = self.client.get(
            "/",
            headers={
                "X-Auth-Token": "admin",
                "OpenStack-API-Version": "placement latest",
            },
        )
        self.assertEqual(response.status_code, 200)
        expected = "placement 1.%d" % microversion.MAX_SUPPORTED_MINOR
        self.assertIn(expected, response.headers["OpenStack-API-Version"])

    def test_vary_header_present(self):
        """Test Vary header is set for microversion negotiation."""
        response = self.client.get("/", headers={"X-Auth-Token": "admin"})
        self.assertEqual(response.headers.get("Vary"), "OpenStack-API-Version")

    def test_accept_header_missing_ok_root(self):
        """Test request with no Accept header succeeds on root."""
        response = self.client.get("/", headers={"X-Auth-Token": "admin"})
        self.assertNotEqual(response.status_code, 406)


class TestContentTypeValidation(base.BaseTestCase):
    """Tests for Content-Type validation middleware."""

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def setUp(self, mock_init_neo4j):
        """Set up test fixtures."""
        super().setUp()
        self.app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})
        self.client = self.app.test_client()
        # Mock the driver for endpoints that need it
        self.mock_driver = mock.MagicMock()
        self.app.extensions["neo4j_driver"] = self.mock_driver

    def test_post_requires_json_content_type(self):
        """Test POST with wrong content type returns 415."""
        response = self.client.post(
            "/resource_providers",
            data="name=test",
            headers={"X-Auth-Token": "admin", "Content-Type": "text/plain"},
        )
        self.assertEqual(response.status_code, 415)

    def test_get_no_content_type_required(self):
        """Test GET requests don't require Content-Type."""
        # Mock session for resource_providers endpoint
        mock_session = mock.MagicMock()
        mock_session.__enter__ = mock.MagicMock(return_value=mock_session)
        mock_session.__exit__ = mock.MagicMock(return_value=False)
        mock_session.run.return_value = []
        self.mock_driver.session.return_value = mock_session

        response = self.client.get(
            "/resource_providers", headers={"X-Auth-Token": "admin"}
        )
        self.assertNotEqual(response.status_code, 415)


class TestAcceptsJsonHelper(base.BaseTestCase):
    """Tests for _accepts_json helper function."""

    @mock.patch.object(app, "_init_neo4j", autospec=True)
    def setUp(self, mock_init_neo4j):
        """Set up test fixtures."""
        super().setUp()
        self.app = app.create_app({"TESTING": True, "SKIP_DB_INIT": True})

    def test_accepts_json_application_json(self):
        """Test Accept: application/json is accepted."""
        with self.app.test_request_context("/", headers={"Accept": "application/json"}):
            from tachyon.api import middleware

            self.assertTrue(middleware._accepts_json())

    def test_accepts_json_wildcard(self):
        """Test Accept: */* is accepted."""
        with self.app.test_request_context("/", headers={"Accept": "*/*"}):
            from tachyon.api import middleware

            self.assertTrue(middleware._accepts_json())

    def test_accepts_json_application_wildcard(self):
        """Test Accept: application/* is accepted."""
        with self.app.test_request_context("/", headers={"Accept": "application/*"}):
            from tachyon.api import middleware

            self.assertTrue(middleware._accepts_json())

    def test_accepts_json_empty_header(self):
        """Test empty Accept header is accepted (default)."""
        with self.app.test_request_context("/", headers={"Accept": ""}):
            from tachyon.api import middleware

            self.assertTrue(middleware._accepts_json())

    def test_accepts_json_no_header(self):
        """Test no Accept header is accepted."""
        with self.app.test_request_context("/"):
            from tachyon.api import middleware

            self.assertTrue(middleware._accepts_json())

    def test_rejects_text_html(self):
        """Test Accept: text/html is rejected."""
        with self.app.test_request_context("/", headers={"Accept": "text/html"}):
            from tachyon.api import middleware

            self.assertFalse(middleware._accepts_json())
