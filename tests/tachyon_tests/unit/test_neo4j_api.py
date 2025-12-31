# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Tachyon Neo4j API module."""

from unittest import mock

from oslotest import base

from tachyon.db import neo4j_api


class TestNeo4jClient(base.BaseTestCase):
    """Tests for Neo4jClient class."""

    @mock.patch("neo4j.GraphDatabase.driver", autospec=True)
    def test_client_creation_with_auth(self, mock_driver):
        """Test Neo4jClient creation with username and password."""
        client = neo4j_api.Neo4jClient(
            uri="bolt://localhost:7687", username="neo4j", password="password"
        )

        mock_driver.assert_called_once_with(
            "bolt://localhost:7687", auth=("neo4j", "password")
        )
        self.assertIsNotNone(client)

    @mock.patch("neo4j.GraphDatabase.driver", autospec=True)
    def test_client_creation_without_auth(self, mock_driver):
        """Test Neo4jClient creation without authentication."""
        client = neo4j_api.Neo4jClient(uri="bolt://localhost:7687")

        mock_driver.assert_called_once_with("bolt://localhost:7687", auth=None)
        self.assertIsNotNone(client)

    @mock.patch("neo4j.GraphDatabase.driver", autospec=True)
    def test_session_context_manager(self, mock_driver):
        """Test Neo4jClient session context manager."""
        mock_session = mock.MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = mock.MagicMock(
            return_value=mock_session
        )
        mock_driver.return_value.session.return_value.__exit__ = mock.MagicMock(
            return_value=False
        )

        client = neo4j_api.Neo4jClient(
            uri="bolt://localhost:7687", username="neo4j", password="password"
        )

        with client.session() as session:
            self.assertIsNotNone(session)

    @mock.patch("neo4j.GraphDatabase.driver", autospec=True)
    def test_close_driver(self, mock_driver):
        """Test Neo4jClient close method."""
        client = neo4j_api.Neo4jClient(
            uri="bolt://localhost:7687", username="neo4j", password="password"
        )

        client.close()
        mock_driver.return_value.close.assert_called_once()


class TestInitDriver(base.BaseTestCase):
    """Tests for init_driver function."""

    @mock.patch("neo4j.GraphDatabase.driver", autospec=True)
    def test_init_driver_returns_client(self, mock_driver):
        """Test init_driver returns a Neo4jClient instance."""
        client = neo4j_api.init_driver(
            uri="bolt://localhost:7687", username="neo4j", password="password"
        )

        self.assertIsInstance(client, neo4j_api.Neo4jClient)

    @mock.patch("neo4j.GraphDatabase.driver", autospec=True)
    def test_init_driver_passes_credentials(self, mock_driver):
        """Test init_driver passes credentials to driver."""
        neo4j_api.init_driver(
            uri="bolt://localhost:7687", username="testuser", password="testpass"
        )

        mock_driver.assert_called_with(
            "bolt://localhost:7687", auth=("testuser", "testpass")
        )
