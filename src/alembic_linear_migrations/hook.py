"""Alembic ``post_write_hook`` entry point.

Wired into ``alembic.ini`` as::

    [post_write_hooks]
    hooks = alembic_linear
    alembic_linear.type = console_scripts
    alembic_linear.entrypoint = alembic-linear-update

Alembic passes the path of the revision script it just wrote as the first
argument, and prepends it automatically when the hook's ``options`` do not
mention ``REVISION_SCRIPT_FILENAME``. The path is not needed to compute the
head -- that comes from the graph -- but it anchors the search for
``alembic.ini`` to the migration tree rather than to whatever directory the
developer happened to run ``alembic revision`` from.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from . import AlembicLinearError
from .commands import update
from .config import discover

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    start: Path | None = None
    if args:
        revision_script = Path(args[0])
        if revision_script.is_file():
            start = revision_script.parent

    try:
        project = discover(start=start)
        changed = update(project)
    except AlembicLinearError as exc:
        # Alembic does not check this exit code, so stderr is what the
        # developer actually sees. The pre-commit hook is the backstop.
        print(f"alembic-linear: {exc}", file=sys.stderr)
        return 1

    if changed:
        print(f"alembic-linear: updated {project.head_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
