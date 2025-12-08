import io
import logging

import fixtures


class Logging(fixtures.Fixture):
    """Capture logging output."""

    def _setUp(self):
        self.logger = logging.getLogger()
        self.stream = io.StringIO()
        handler = logging.StreamHandler(self.stream)
        self.logger.addHandler(handler)
        self.addCleanup(self.logger.removeHandler, handler)
