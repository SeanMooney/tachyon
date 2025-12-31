# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Tachyon microversion module."""

from oslotest import base

from tachyon.api import microversion


class TestMicroversion(base.BaseTestCase):
    """Tests for Microversion dataclass."""

    def test_microversion_creation(self):
        """Test creating a Microversion instance."""
        mv = microversion.Microversion(1, 15)
        self.assertEqual(mv.major, 1)
        self.assertEqual(mv.minor, 15)

    def test_microversion_is_at_least_true(self):
        """Test is_at_least returns True when version is sufficient."""
        mv = microversion.Microversion(1, 20)
        self.assertTrue(mv.is_at_least(15))
        self.assertTrue(mv.is_at_least(20))

    def test_microversion_is_at_least_false(self):
        """Test is_at_least returns False when version is insufficient."""
        mv = microversion.Microversion(1, 10)
        self.assertFalse(mv.is_at_least(15))

    def test_microversion_comparison(self):
        """Test Microversion comparison operators."""
        mv1 = microversion.Microversion(1, 10)
        mv2 = microversion.Microversion(1, 15)
        mv3 = microversion.Microversion(1, 10)

        self.assertTrue(mv1 < mv2)
        self.assertTrue(mv2 > mv1)
        self.assertEqual(mv1, mv3)

    def test_microversion_immutable(self):
        """Test that Microversion is immutable (frozen)."""
        mv = microversion.Microversion(1, 10)
        with self.assertRaises(AttributeError):
            mv.minor = 15


class TestMicroversionParse(base.BaseTestCase):
    """Tests for microversion parse function."""

    def test_parse_none_returns_default(self):
        """Test parsing None returns default version 1.0."""
        mv = microversion.parse(None)
        self.assertEqual(mv, microversion.Microversion(1, 0))

    def test_parse_empty_string_returns_default(self):
        """Test parsing empty string returns default version 1.0."""
        mv = microversion.parse("")
        self.assertEqual(mv, microversion.Microversion(1, 0))

    def test_parse_valid_version(self):
        """Test parsing a valid microversion string."""
        mv = microversion.parse("placement 1.15")
        self.assertEqual(mv.major, 1)
        self.assertEqual(mv.minor, 15)

    def test_parse_latest(self):
        """Test parsing 'latest' microversion."""
        mv = microversion.parse("placement latest")
        self.assertEqual(mv.major, 1)
        self.assertEqual(mv.minor, microversion.LATEST_MINOR)

    def test_parse_latest_case_insensitive(self):
        """Test parsing 'LATEST' is case insensitive."""
        mv = microversion.parse("placement LATEST")
        self.assertEqual(mv.minor, microversion.LATEST_MINOR)

    def test_parse_invalid_format_returns_default(self):
        """Test parsing invalid format returns default version."""
        mv = microversion.parse("invalid")
        self.assertEqual(mv, microversion.Microversion(1, 0))

    def test_parse_wrong_service_returns_default(self):
        """Test parsing wrong service type returns default."""
        mv = microversion.parse("compute 2.1")
        self.assertEqual(mv, microversion.Microversion(1, 0))


class TestMicroversionConstants(base.BaseTestCase):
    """Tests for microversion constants."""

    def test_max_supported_minor(self):
        """Test MAX_SUPPORTED_MINOR is set correctly."""
        self.assertEqual(microversion.MAX_SUPPORTED_MINOR, 39)

    def test_latest_minor_is_high(self):
        """Test LATEST_MINOR is higher than any real version."""
        self.assertGreater(microversion.LATEST_MINOR, microversion.MAX_SUPPORTED_MINOR)
