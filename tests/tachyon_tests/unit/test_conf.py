# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Tachyon configuration module."""

from oslo_config import cfg
from oslotest import base

from tachyon import conf


class TestConfigOptions(base.BaseTestCase):
    """Tests for configuration options."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        # Create a fresh ConfigOpts for testing
        self.test_conf = cfg.ConfigOpts()
        conf.register_opts(self.test_conf)

    def test_api_opts_registered(self):
        """Test that API options are registered."""
        self.assertIsNotNone(self.test_conf.api)

    def test_neo4j_opts_registered(self):
        """Test that Neo4j options are registered."""
        self.assertIsNotNone(self.test_conf.neo4j)

    def test_auth_strategy_default(self):
        """Test auth_strategy default value."""
        self.assertEqual(self.test_conf.api.auth_strategy, "keystone")

    def test_auth_strategy_choices(self):
        """Test auth_strategy valid choices."""
        # Setting to valid value should work
        self.test_conf.set_override("auth_strategy", "noauth2", group="api")
        self.assertEqual(self.test_conf.api.auth_strategy, "noauth2")

    def test_max_limit_default(self):
        """Test max_limit default value."""
        self.assertEqual(self.test_conf.api.max_limit, 1000)

    def test_max_limit_positive(self):
        """Test max_limit must be positive."""
        self.test_conf.set_override("max_limit", 500, group="api")
        self.assertEqual(self.test_conf.api.max_limit, 500)

    def test_auto_apply_schema_default(self):
        """Test auto_apply_schema default value."""
        self.assertTrue(self.test_conf.api.auto_apply_schema)

    def test_neo4j_uri_default(self):
        """Test Neo4j URI default value."""
        self.assertEqual(self.test_conf.neo4j.uri, "bolt://localhost:7687")

    def test_neo4j_username_default(self):
        """Test Neo4j username default value."""
        self.assertEqual(self.test_conf.neo4j.username, "neo4j")

    def test_neo4j_password_default(self):
        """Test Neo4j password default value."""
        self.assertEqual(self.test_conf.neo4j.password, "password")


class TestListOpts(base.BaseTestCase):
    """Tests for list_opts function."""

    def test_list_opts_returns_list(self):
        """Test list_opts returns a list."""
        opts = conf.list_opts()
        self.assertIsInstance(opts, list)

    def test_list_opts_contains_groups(self):
        """Test list_opts contains expected groups."""
        opts = conf.list_opts()
        groups = [group for group, _ in opts]
        self.assertIn("api", groups)
        self.assertIn("neo4j", groups)

    def test_list_opts_api_options(self):
        """Test list_opts includes API options."""
        opts = conf.list_opts()
        api_opts = next(opts for group, opts in opts if group == "api")
        opt_names = [opt.name for opt in api_opts]
        self.assertIn("auth_strategy", opt_names)
        self.assertIn("max_limit", opt_names)

    def test_list_opts_neo4j_options(self):
        """Test list_opts includes Neo4j options."""
        opts_list = conf.list_opts()
        neo4j_opts = next(opts for group, opts in opts_list if group == "neo4j")
        opt_names = [opt.name for opt in neo4j_opts]
        self.assertIn("uri", opt_names)
        self.assertIn("username", opt_names)
        self.assertIn("password", opt_names)
