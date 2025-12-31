# SPDX-License-Identifier: Apache-2.0

"""Neo4j database client wrapper."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import Any

import neo4j
from oslo_log import log

LOG = log.getLogger(__name__)


class Neo4jClient:
    """Lightweight Neo4j driver wrapper.

    Provides a simple context manager interface for Neo4j sessions.
    """

    def __init__(
        self, uri: str, username: str | None = None, password: str | None = None
    ) -> None:
        """Initialize the Neo4j client.

        :param uri: Neo4j database URI (bolt://...)
        :param username: Optional database username
        :param password: Optional database password
        """
        LOG.debug("Connecting to Neo4j at %s", uri)
        auth: tuple[str, str] | None = None
        if username and password:
            auth = (username, password)
        self._driver: neo4j.Driver = neo4j.GraphDatabase.driver(uri, auth=auth)
        LOG.info("Neo4j driver created for %s", uri)

    @contextlib.contextmanager
    def session(self) -> Generator[Any, None, None]:
        """Create a database session context manager.

        :yields: Neo4j session
        """
        with self._driver.session() as session:
            yield session

    def close(self) -> None:
        """Close the database driver."""
        LOG.debug("Closing Neo4j driver")
        self._driver.close()


def init_driver(uri: str, username: str | None, password: str | None) -> Neo4jClient:
    """Initialize a Neo4j client.

    :param uri: Neo4j database URI
    :param username: Database username
    :param password: Database password
    :returns: Neo4jClient instance
    """
    return Neo4jClient(uri, username, password)
