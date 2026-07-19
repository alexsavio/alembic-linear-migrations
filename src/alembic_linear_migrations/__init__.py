"""Record the Alembic migration graph head in a tracked file.

Two branches that each add a migration from the same parent produce a git
conflict in ``head.txt`` at the moment the branches meet, instead of an
Alembic ``Multiple head revisions are present`` error days later.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["AlembicLinearError", "__version__"]

try:
    __version__ = version("alembic-linear-migrations")
except PackageNotFoundError:  # pragma: no cover - only from an uninstalled source tree
    __version__ = "0.0.0"


class AlembicLinearError(Exception):
    """Base class for every error this package reports to the user.

    The message is printed verbatim to stderr by the CLI, so it must read as
    a complete explanation on its own.
    """
