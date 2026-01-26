# SPDX-License-Identifier: Apache-2.0

"""Common functions used by Tachyon CLI interfaces.

Based on nova/cmd/common.py patterns for oslo.config subcommand handling.
"""

from __future__ import annotations

import argparse
import inspect
from typing import Any
from typing import Callable

from oslo_config import cfg

CONF = cfg.CONF


class MissingArgs(Exception):
    """Exception for missing required arguments."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        msg = f"Missing argument(s): {', '.join(missing)}"
        super().__init__(msg)


def validate_args(
    fn: Callable[..., Any], *args: Any, **kwargs: Any
) -> list[str]:
    """Check that the supplied args are sufficient for calling a function.

    :param fn: the function to check
    :param args: the positional arguments supplied
    :param kwargs: the keyword arguments supplied
    :returns: list of missing argument names
    """
    argspec = inspect.getfullargspec(fn)

    num_defaults = len(argspec.defaults or [])
    required_args = argspec.args[: len(argspec.args) - num_defaults]

    # Remove 'self' for bound methods
    if hasattr(fn, "__self__") and fn.__self__ is not None:
        required_args = required_args[1:]

    missing = [arg for arg in required_args if arg not in kwargs]
    missing = missing[len(args) :]
    return missing


def args(*args: Any, **kwargs: Any) -> Callable[..., Any]:
    """Decorator which adds the given args and kwargs to the args list.

    The args list is stored in the function's __dict__ and used by
    add_command_parsers to build argparse arguments.

    :param args: positional arguments for argparse.add_argument
    :param kwargs: keyword arguments for argparse.add_argument
    :returns: decorator function
    """

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func.__dict__.setdefault("args", []).insert(0, (args, kwargs))
        return func

    return _decorator


def action_description(text: str) -> Callable[..., Any]:
    """Decorator for adding a description to command action.

    :param text: description text for the action
    :returns: decorator function
    """

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func.description = text  # type: ignore[attr-defined]
        return func

    return _decorator


def methods_of(obj: object) -> list[tuple[str, Callable[..., Any]]]:
    """Get all callable methods of an object that don't start with underscore.

    :param obj: object to inspect
    :returns: list of tuples of (method_name, method)
    """
    result = []
    for name in dir(obj):
        if callable(getattr(obj, name)) and not name.startswith("_"):
            result.append((name, getattr(obj, name)))
    return result


def add_command_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    categories: dict[str, type],
) -> None:
    """Add command parsers to the given subparsers.

    Adds a parser with subparsers for each category in the categories dict.

    :param subparsers: argparse subparsers action
    :param categories: dict mapping category names to command classes
    """
    # Add version parser
    subparsers.add_parser("version")

    # Add bash-completion parser
    parser = subparsers.add_parser("bash-completion")
    parser.add_argument("query_category", nargs="?")

    for category in categories:
        command_object = categories[category]()

        desc = getattr(command_object, "description", None)
        parser = subparsers.add_parser(category, description=desc)
        parser.set_defaults(command_object=command_object)

        category_subparsers = parser.add_subparsers(dest="action")
        category_subparsers.required = True

        for action, action_fn in methods_of(command_object):
            action_parser = category_subparsers.add_parser(
                action, description=getattr(action_fn, "description", desc)
            )

            action_kwargs: list[str] = []
            for fn_args, fn_kwargs in getattr(action_fn, "args", []):
                # Handle positional vs optional arguments
                if fn_args[0] != fn_args[0].lstrip("-"):
                    fn_kwargs.setdefault("dest", fn_args[0].lstrip("-"))
                    if fn_kwargs["dest"].startswith("action_kwarg_"):
                        action_kwargs.append(
                            fn_kwargs["dest"][len("action_kwarg_") :]
                        )
                    else:
                        action_kwargs.append(fn_kwargs["dest"])
                        fn_kwargs["dest"] = "action_kwarg_" + fn_kwargs["dest"]
                else:
                    action_kwargs.append(fn_args[0])
                    fn_args = tuple("action_kwarg_" + arg for arg in fn_args)

                action_parser.add_argument(*fn_args, **fn_kwargs)

            action_parser.set_defaults(action_fn=action_fn)
            action_parser.set_defaults(action_kwargs=action_kwargs)

            action_parser.add_argument(
                "action_args", nargs="*", help=argparse.SUPPRESS
            )


def print_bash_completion(categories: dict[str, type]) -> None:
    """Print bash completion suggestions.

    :param categories: dict mapping category names to command classes
    """
    if not CONF.category.query_category:
        print(" ".join(categories.keys()))
    elif CONF.category.query_category in categories:
        fn = categories[CONF.category.query_category]
        command_object = fn()
        actions = methods_of(command_object)
        print(" ".join([k for (k, v) in actions]))


def get_action_fn() -> tuple[
    Callable[..., Any], list[Any], dict[str, Any]
]:
    """Get the action function and its arguments from parsed config.

    :returns: tuple of (function, positional_args, keyword_args)
    :raises MissingArgs: if required arguments are missing
    """
    fn = CONF.category.action_fn
    fn_args: list[Any] = []
    for arg in CONF.category.action_args:
        if isinstance(arg, bytes):
            arg = arg.decode("utf-8")
        fn_args.append(arg)

    fn_kwargs: dict[str, Any] = {}
    for k in CONF.category.action_kwargs:
        v = getattr(CONF.category, "action_kwarg_" + k)
        if v is None:
            continue
        if isinstance(v, bytes):
            v = v.decode("utf-8")
        fn_kwargs[k] = v

    # Validate arguments
    missing = validate_args(fn, *fn_args, **fn_kwargs)
    if missing:
        print(fn.__doc__)
        CONF.print_help()
        raise MissingArgs(missing)

    return fn, fn_args, fn_kwargs
