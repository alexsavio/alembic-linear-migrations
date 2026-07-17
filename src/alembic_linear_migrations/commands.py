"""The ``update`` and ``check`` commands."""

from __future__ import annotations

from collections.abc import Sequence

from alembic.script import ScriptDirectory

from . import AlembicLinearError
from . import head as head_file
from .config import Project

__all__ = ["check", "single_head", "update"]

_BRANCH_LABEL_NOTE = (
    "If this project deliberately uses Alembic branch labels and expects more\n"
    "than one head, alembic-linear-migrations is not the right tool for it: it\n"
    "only models linear histories."
)


def _describe(
    project: Project, script: ScriptDirectory, revisions: Sequence[str]
) -> str:
    lines = []
    for revision in revisions:
        name = project.script_path(script.get_revision(revision)).name
        lines.append(f"  {revision}  {name}")
    return "\n".join(lines)


def single_head(project: Project, script: ScriptDirectory) -> str:
    """Return the one head of the graph, or explain why there isn't one."""
    heads = project.heads(script)

    if len(heads) == 1:
        return heads[0]

    if not heads:
        raise AlembicLinearError(
            f"No migrations found under {project.script_dir}.\n"
            f"There is no head to record yet."
        )

    raise AlembicLinearError(
        f"The migration graph has {len(heads)} heads:\n"
        f"{_describe(project, script, heads)}\n\n"
        f"Two branches added a migration from the same parent. Resolve with:\n"
        f"  alembic-linear rebase\n\n"
        f"{_BRANCH_LABEL_NOTE}"
    )


def update(project: Project) -> bool:
    """Recompute ``head.txt`` from the graph. Returns True if the file changed."""
    script = project.load_script()
    revision = single_head(project, script)
    return head_file.write(project.head_file, revision)


def check(project: Project) -> None:
    """Raise unless the graph has one head and ``head.txt`` already records it."""
    script = project.load_script()
    revision = single_head(project, script)
    recorded = head_file.read(project.head_file)

    if recorded != revision:
        raise AlembicLinearError(
            f"{project.head_file} is stale.\n"
            f"  recorded: {recorded}\n"
            f"  actual:   {revision}\n\n"
            f"Run:  alembic-linear update"
        )
