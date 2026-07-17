"""Command line interface: ``alembic-linear <update|check|rebase>``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import AlembicLinearError, __version__
from .commands import check, update
from .config import discover
from .rebase import rebase

__all__ = ["main"]

_CONFIG_HELP = "path to alembic.ini (default: search upward from the working directory)"


def _add_config_arg(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    # Subparsers use SUPPRESS so that omitting -c after the subcommand leaves
    # any value given before it intact, instead of overwriting it with None.
    parser.add_argument(
        "-c",
        "--config",
        metavar="PATH",
        default=argparse.SUPPRESS if suppress else None,
        help=_CONFIG_HELP,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alembic-linear",
        description=(
            "Keep the Alembic migration graph linear by recording its head in "
            "a tracked file, so that two branches adding a migration from the "
            "same parent collide in git instead of in production."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    _add_config_arg(parser, suppress=False)

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    update_parser = subparsers.add_parser(
        "update", help="recompute head.txt from the migration graph"
    )
    _add_config_arg(update_parser, suppress=True)
    update_parser.add_argument(
        "--exit-on-change",
        action="store_true",
        help="exit 1 if head.txt had to be rewritten (for pre-commit)",
    )

    check_parser = subparsers.add_parser(
        "check", help="exit 1 if the graph has multiple heads or head.txt is stale"
    )
    _add_config_arg(check_parser, suppress=True)

    rebase_parser = subparsers.add_parser(
        "rebase", help="resolve a head.txt conflict between two branches"
    )
    _add_config_arg(rebase_parser, suppress=True)
    rebase_parser.add_argument(
        "--onto",
        metavar="REVISION",
        help=(
            "the head to rebase onto, i.e. the other branch's revision. "
            "Required when no merge or rebase is in progress for this to "
            "be inferred from."
        ),
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    try:
        project = discover(args.config)

        if args.command == "update":
            changed = update(project)
            if changed:
                print(f"Updated {project.head_file}")
                if args.exit_on_change:
                    return 1
            else:
                print(f"{project.head_file} is up to date")
            return 0

        if args.command == "check":
            check(project)
            print(f"{project.head_file} is up to date")
            return 0

        if args.command == "rebase":
            result = rebase(project, onto=args.onto)
            print(result.summary())
            return 0

    except AlembicLinearError as exc:
        print(f"alembic-linear: {exc}", file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
