"""Fixture Alembic projects, built on disk without invoking the alembic CLI."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

# Booby-trapped on purpose. Reading the graph must stay static: no database, no
# application imports, so that a pre-commit hook works with no app environment.
# Any code path that imports env.py fails loudly here instead of silently
# acquiring a dependency on the app being importable.
ENV_PY = """\
raise AssertionError(
    "env.py was imported. Reading the migration graph must stay static."
)
"""

SCRIPT_MAKO = '''\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from typing import Union

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''

ANNOTATED_TEMPLATE = '''\
"""{message}

Revision ID: {revision}
Revises: {down}
"""
from typing import Union

revision: str = {revision!r}
down_revision: Union[str, None] = {down!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''

BARE_TEMPLATE = '''\
"""{message}

Revision ID: {revision}
Revises: {down}
"""

revision = {revision!r}
down_revision = {down!r}
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
'''


class AlembicProject:
    """A throwaway Alembic project rooted at ``root``."""

    def __init__(self, root: Path, script_location: str) -> None:
        self.root = root
        self.script_dir = root / "migrations"
        self.versions = self.script_dir / "versions"
        self.ini = root / "alembic.ini"
        self.head_file = self.script_dir / "head.txt"

        self.versions.mkdir(parents=True)
        (self.script_dir / "env.py").write_text(ENV_PY, encoding="utf-8")
        (self.script_dir / "script.py.mako").write_text(SCRIPT_MAKO, encoding="utf-8")
        self.ini.write_text(
            f"[alembic]\nscript_location = {script_location}\n", encoding="utf-8"
        )

    def add_revision(
        self,
        revision: str,
        down: str | None,
        message: str = "fixture",
        *,
        annotated: bool = True,
    ) -> Path:
        template = ANNOTATED_TEMPLATE if annotated else BARE_TEMPLATE
        path = self.versions / f"{revision}_{message.replace(' ', '_')}.py"
        path.write_text(
            template.format(revision=revision, down=down, message=message),
            encoding="utf-8",
        )
        return path

    def add_chain(self, *revisions: str, down: str | None = None) -> None:
        previous = down
        for revision in revisions:
            self.add_revision(revision, previous, message=revision)
            previous = revision

    def write_head(self, revision: str) -> None:
        from alembic_linear_migrations import head

        self.head_file.write_text(head.render(revision), encoding="utf-8")


MakeProject = Callable[..., AlembicProject]
Git = Callable[..., str]


@pytest.fixture
def make_project(tmp_path: Path) -> MakeProject:
    """Build an Alembic project; ``script_location`` style is selectable."""

    def _make(
        name: str = "app", script_location: str = "%(here)s/migrations"
    ) -> AlembicProject:
        root = tmp_path / name
        root.mkdir()
        return AlembicProject(root, script_location)

    return _make


@pytest.fixture
def project(make_project: MakeProject) -> AlembicProject:
    """A linear three-migration project with an accurate head.txt."""
    project = make_project()
    project.add_chain("aaaa", "bbbb", "cccc")
    project.write_head("cccc")
    return project


@pytest.fixture
def in_dir() -> Iterator[None]:
    """Restore the working directory after a test changes it."""
    previous = Path.cwd()
    yield
    os.chdir(previous)


@pytest.fixture
def git() -> Git:
    """Run git with a fixed identity, so tests never read the user's config."""

    def _git(*args: str, cwd: Path) -> str:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout

    return _git
