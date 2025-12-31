"""Tachyon configuration options.

This module defines configuration options for the Tachyon service using
oslo.config. Options are organized into groups following OpenStack patterns.
"""

from __future__ import annotations

from typing import Any

from oslo_config import cfg
from oslo_log import log

LOG = log.getLogger(__name__)

CONF = cfg.CONF

api_opts: list[cfg.Opt] = [
    cfg.StrOpt(
        "auth_strategy",
        default="keystone",
        choices=["keystone", "noauth2"],
        help="Authentication strategy for the API service.",
    ),
    cfg.IntOpt(
        "max_limit",
        default=1000,
        min=1,
        help="Maximum number of items returned in a single response.",
    ),
    cfg.BoolOpt(
        "auto_apply_schema",
        default=True,
        help="Automatically apply Neo4j schema on startup.",
    ),
]

neo4j_opts: list[cfg.Opt] = [
    cfg.URIOpt(
        "uri", default="bolt://localhost:7687", help="Neo4j database connection URI."
    ),
    cfg.StrOpt("username", default="neo4j", help="Neo4j database username."),
    cfg.StrOpt(
        "password", default="password", secret=True, help="Neo4j database password."
    ),
]


def register_opts(conf: cfg.ConfigOpts) -> None:
    """Register configuration options with a ConfigOpts instance.

    :param conf: oslo.config ConfigOpts instance
    """
    LOG.debug("Registering configuration options")
    conf.register_opts(api_opts, group="api")
    conf.register_opts(neo4j_opts, group="neo4j")


def list_opts() -> list[tuple[str, list[Any]]]:
    """Return a list of oslo.config options.

    This is used for documentation generation (oslo-config-generator).

    :returns: List of (group_name, options) tuples
    """
    return [
        ("api", api_opts),
        ("neo4j", neo4j_opts),
    ]


# Register options on module import for convenience
register_opts(CONF)
