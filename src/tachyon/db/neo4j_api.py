# SPDX-License-Identifier: Apache-2.0

"""Neo4j database client wrapper."""

from __future__ import annotations

import contextlib

import neo4j


class Neo4jClient:
    """Lightweight Neo4j driver wrapper.

    Provides a simple context manager interface for Neo4j sessions.
    """

    def __init__(self, uri, username=None, password=None):
        """Initialize the Neo4j client.

        :param uri: Neo4j database URI (bolt://...)
        :param username: Optional database username
        :param password: Optional database password
        """
        auth = (username, password) if username and password else None
        self._driver = neo4j.GraphDatabase.driver(uri, auth=auth)

    @contextlib.contextmanager
    def session(self):
        """Create a database session context manager.

        :yields: Neo4j session
        """
        with self._driver.session() as session:
            yield session

    def close(self):
        """Close the database driver."""
        self._driver.close()


def init_driver(uri, username, password):
    """Initialize a Neo4j client.

    :param uri: Neo4j database URI
    :param username: Database username
    :param password: Database password
    :returns: Neo4jClient instance
    """
    return Neo4jClient(uri, username, password)
