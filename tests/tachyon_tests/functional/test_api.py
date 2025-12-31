# SPDX-License-Identifier: Apache-2.0

"""Gabbi test loader for Tachyon API."""

import os

import wsgi_intercept
from gabbi import driver
from oslotest import output
from tachyon_tests.functional.local_fixtures import gabbits as fixtures
from tachyon_tests.local_fixtures import logging as capture

wsgi_intercept.STRICT_RESPONSE_HEADERS = True

TESTS_DIR = "gabbits"


def load_tests(loader, tests, pattern):
    test_dir = os.path.join(os.path.dirname(__file__), TESTS_DIR)
    inner_fixtures = [
        output.CaptureOutput,
        capture.Logging,
    ]
    return driver.build_tests(
        test_dir,
        loader,
        host=None,
        test_loader_name=__name__,
        intercept=fixtures.setup_app,
        inner_fixtures=inner_fixtures,
        fixture_module=fixtures,
    )
