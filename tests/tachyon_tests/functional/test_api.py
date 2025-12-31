"""Gabbi test loader for Tachyon API.

This module integrates Gabbi with Flask for declarative YAML-based API testing.
A monkey-patch is applied to gabbi's HTTPTestCase to read the server port from
the TACHYON_TEST_PORT environment variable at request time, enabling each
worker process to use its own dynamically allocated port.
"""

import os

from gabbi import case, driver
from oslotest import output

from tachyon_tests.functional.local_fixtures import gabbits as fixtures
from tachyon_tests.local_fixtures import logging as capture


# Monkey-patch gabbi's HTTPTestCase._parse_url to read port from environment.
# This allows the port to be allocated at fixture time (in each worker process)
# rather than at test discovery time, enabling true parallel execution.
_original_parse_url = case.HTTPTestCase._parse_url


def _patched_parse_url(self, url):
    """Patched _parse_url that reads port from TACHYON_TEST_PORT environment variable.

    This enables dynamic port allocation at fixture time while maintaining
    compatibility with gabbi's test discovery mechanism.
    """
    env_port = os.environ.get('TACHYON_TEST_PORT')
    if env_port:
        self.port = int(env_port)
    return _original_parse_url(self, url)


case.HTTPTestCase._parse_url = _patched_parse_url


TESTS_DIR = "gabbits"

# Placeholder port used during test discovery.
# The actual port is allocated at fixture time and read via the monkey-patch.
# Note: we are using a placeholder port less than 1024 since that requires root privileges.
# we do not execute the tests as root, so this will fail if the placeholder port is not
# overridden by the actual port.
PLACEHOLDER_PORT = 42


def load_tests(loader, tests, pattern):
    """Provide a TestSuite to the discovery process.

    This is the standard Python unittest load_tests protocol.
    Called by test runners (stestr, unittest discover).

    The port parameter is a placeholder - the actual port is allocated
    at fixture time and read from TACHYON_TEST_PORT environment variable
    via the monkey-patched _parse_url method.

    Args:
        loader: unittest.TestLoader instance
        tests: Existing TestSuite (ignored, Gabbi builds its own)
        pattern: Pattern for test discovery (ignored)

    Returns:
        TestSuite containing Gabbi tests generated from YAML files
    """
    test_dir = os.path.join(os.path.dirname(__file__), TESTS_DIR)
    inner_fixtures = [
        output.CaptureOutput,
        capture.Logging,
    ]
    return driver.build_tests(
        test_dir,
        loader,
        host='127.0.0.1',
        port=PLACEHOLDER_PORT,
        test_loader_name=__name__,
        inner_fixtures=inner_fixtures,
        fixture_module=fixtures,
    )
