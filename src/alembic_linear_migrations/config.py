"""Locate ``alembic.ini`` and resolve the migration graph from it.

Everything here goes through :meth:`ScriptDirectory.from_config`, which reads
the migration scripts statically. It never executes ``env.py``, so it needs no
database and cannot import application code -- the property that lets this run
inside a pre-commit hook with no app environment.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator, Sequence
from pathlib import Path

from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util import CommandError

from . import AlembicLinearError

__all__ = ["HEAD_FILENAME", "Project", "discover"]

HEAD_FILENAME = "head.txt"

CONFIG_FILENAME = "alembic.ini"


@contextlib.contextmanager
def _chdir(target: Path) -> Iterator[None]:
    """Run a block with ``target`` as the working directory.

    Alembic resolves a relative ``script_location`` (and ``version_locations``,
    and ``prepend_sys_path``) against the working directory, which is why it
    expects to be invoked from the directory holding ``alembic.ini``. A
    pre-commit hook runs from the repository root and a post_write_hook
    inherits whatever directory the developer typed the command in, so neither
    can rely on that. Borrowing the directory for the duration of the read
    makes every relative path resolve the way the ini file's author meant it.
    """
    previous = Path.cwd()
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(previous)


def _find_config_file(explicit: str | None, start: Path | None) -> Path:
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise AlembicLinearError(f"No such config file: {path}")
        return path.resolve()

    origin = (start or Path.cwd()).resolve()
    for directory in (origin, *origin.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    raise AlembicLinearError(
        f"No {CONFIG_FILENAME} found in {origin} or any parent directory.\n"
        f"Pass one explicitly with:  alembic-linear --config path/to/{CONFIG_FILENAME}"
    )


def _read_graph(config_path: Path) -> ScriptDirectory:
    """Build a ScriptDirectory, restating alembic's own errors as ours.

    Alembic raises for an unreadable config, a missing script_location, or a
    broken graph. Those messages are good; they just arrive as exception types
    the CLI would render as a traceback.
    """
    try:
        script = ScriptDirectory.from_config(Config(str(config_path)))
        # Read every revision file now, while relative version_locations still
        # resolve against the config file's directory. `revision_map` alone
        # only builds a lazy map; `.heads` is what forces it to load.
        script.revision_map.heads  # noqa: B018
        return script
    except (CommandError, RevisionError) as exc:
        raise AlembicLinearError(
            f"Alembic could not read {config_path}:\n  {exc}"
        ) from exc
    except Exception as exc:
        # Reading revision ids means importing each migration module, which runs
        # whatever is at its top level. Anything can come back out of that, and a
        # traceback would bury the one thing worth saying.
        raise AlembicLinearError(
            f"Reading the migration graph raised {type(exc).__name__}: {exc}\n\n"
            f"Alembic imports every migration file to read its revision ids, so a\n"
            f"migration that imports application code only loads where that code\n"
            f"is importable. A pre-commit hook runs in its own environment, which\n"
            f"has alembic but not your app; to use yours instead, declare the hook\n"
            f"with `repo: local` and `language: system`."
        ) from exc


class Project:
    """An Alembic project: its config file, script directory, and head file."""

    def __init__(self, config_path: Path, script_dir: Path) -> None:
        self.config_path = config_path
        self.script_dir = script_dir
        self.head_file = script_dir / HEAD_FILENAME

    @property
    def root(self) -> Path:
        """The directory holding ``alembic.ini``; relative paths anchor here."""
        return self.config_path.parent

    def load_script(self) -> ScriptDirectory:
        """Read the migration graph fresh from disk.

        ``ScriptDirectory`` memoizes its revision map on first access, so a new
        instance is required after any command rewrites a migration file.
        """
        with _chdir(self.root):
            return _read_graph(self.config_path)

    def script_path(self, script: Script) -> Path:
        """Absolute path of a revision file, whatever alembic recorded."""
        path = Path(script.path)
        if not path.is_absolute():
            path = self.root / path
        return path.resolve()

    def heads(self, script: ScriptDirectory) -> Sequence[str]:
        return tuple(script.get_heads())


def discover(config_arg: str | None = None, start: Path | None = None) -> Project:
    """Find the Alembic project to act on.

    Uses ``config_arg`` when given, else searches upward from ``start`` (or the
    working directory) for ``alembic.ini``.
    """
    config_path = _find_config_file(config_arg, start)
    with _chdir(config_path.parent):
        script_dir = Path(_read_graph(config_path).dir).resolve()
    return Project(config_path, script_dir)
