# SPDX-License-Identifier: Apache-2.0

"""CLI interface for tachyon management.

Usage:
    tachyon-manage db sync      # Apply database schema
    tachyon-manage db version   # Print schema info
    tachyon-manage version      # Print tachyon version
"""

from __future__ import annotations

import functools
import sys
import traceback

from oslo_config import cfg
from oslo_log import log as logging

from tachyon import conf  # noqa: F401 - registers config options
from tachyon.cmd import common as cmd_common
from tachyon.db import neo4j_api
from tachyon.db import schema

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

# Suppress verbose logging for CLI commands
_EXTRA_DEFAULT_LOG_LEVELS = [
    "tachyon=WARNING",
    "neo4j=WARNING",
]


class DbCommands:
    """Class for managing the Neo4j database."""

    description = "Database management commands"

    def sync(self) -> int:
        """Sync the database schema (constraints and indexes).

        Applies all schema constraints and indexes to the Neo4j database.
        This command is idempotent - safe to run multiple times.
        """
        print("Connecting to Neo4j...")
        driver = neo4j_api.init_driver(
            CONF.neo4j.uri,
            CONF.neo4j.username,
            CONF.neo4j.password,
        )
        try:
            print("Applying database schema...")
            with driver.session() as session:
                schema.apply_schema(session)
            print("Database schema synced successfully.")
            return 0
        except Exception as e:
            print(f"Error applying schema: {e}")
            return 1
        finally:
            driver.close()

    def version(self) -> int:
        """Print schema information.

        Displays the number and types of schema statements that will be
        applied when running 'db sync'.
        """
        print(f"Schema statements: {len(schema.SCHEMA_STATEMENTS)}")
        print(f"  Uniqueness constraints: {len(schema.UNIQUENESS_CONSTRAINTS)}")
        print(f"  Existence constraints: {len(schema.EXISTENCE_CONSTRAINTS)}")
        print(f"  Indexes: {len(schema.INDEXES)}")
        return 0


CATEGORIES: dict[str, type] = {
    "db": DbCommands,
}


def main() -> int:
    """Parse options and call the appropriate class/method.

    :returns: exit code (0 for success, non-zero for failure)
    """
    # Register subcommand handler
    add_command_parsers = functools.partial(
        cmd_common.add_command_parsers, categories=CATEGORIES
    )
    category_opt = cfg.SubCommandOpt(
        "category",
        title="Command categories",
        help="Available categories",
        handler=add_command_parsers,
    )
    CONF.register_cli_opts([category_opt])

    # Register logging options and parse config
    logging.register_options(CONF)
    try:
        CONF(sys.argv[1:], project="tachyon")
    except cfg.ConfigFilesNotFoundError:
        # Config file is optional for CLI commands
        CONF(sys.argv[1:], project="tachyon", default_config_files=[])

    # Setup logging with reduced verbosity for CLI
    logging.set_defaults(
        default_log_levels=logging.get_default_log_levels()
        + _EXTRA_DEFAULT_LOG_LEVELS
    )
    logging.setup(CONF, "tachyon")

    # Handle special commands
    if CONF.category.name == "version":
        # Import here to avoid circular imports
        try:
            from tachyon import __version__

            print(f"tachyon {__version__}")
        except ImportError:
            print("tachyon (version unknown)")
        return 0

    if CONF.category.name == "bash-completion":
        cmd_common.print_bash_completion(CATEGORIES)
        return 0

    # Execute the requested command
    try:
        fn, fn_args, fn_kwargs = cmd_common.get_action_fn()
        ret = fn(*fn_args, **fn_kwargs)
        return ret if ret is not None else 0
    except cmd_common.MissingArgs as e:
        print(f"Error: {e}")
        return 1
    except Exception:
        print(f"An error has occurred:\n{traceback.format_exc()}")
        return 255


if __name__ == "__main__":
    sys.exit(main())
