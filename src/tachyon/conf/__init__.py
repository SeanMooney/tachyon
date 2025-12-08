from oslo_config import cfg

CONF = cfg.CONF

api_opts = [
    cfg.StrOpt(
        "auth_strategy",
        default="keystone",
        choices=["keystone", "noauth2"],
        help="Authentication strategy",
    ),
    cfg.IntOpt(
        "max_limit",
        default=1000,
        help="Maximum items in a single response.",
    ),
    cfg.StrOpt(
        "neo4j_uri",
        default="bolt://localhost:7687",
        help="Neo4j bolt URI",
    ),
    cfg.StrOpt("neo4j_username", default="neo4j", help="Neo4j username"),
    cfg.StrOpt(
        "neo4j_password", default="password", secret=True, help="Neo4j password"
    ),
]

CONF.register_opts(api_opts, group="api")


def list_opts():
    return [("api", api_opts)]
