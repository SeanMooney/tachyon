from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase, Session


class Neo4jClient:
    """Lightweight Neo4j driver wrapper."""

    def __init__(
        self, uri: str, username: str | None = None, password: str | None = None
    ):
        auth = (username, password) if username and password else None
        self._driver: Driver = GraphDatabase.driver(uri, auth=auth)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._driver.session() as session:
            yield session

    def close(self) -> None:
        self._driver.close()


def init_driver(uri: str, username: str | None, password: str | None) -> Neo4jClient:
    return Neo4jClient(uri, username, password)
