"""Read, write, and parse ``head.txt``.

The file is a comment header plus one bare revision line::

    # alembic-linear-migrations
    # Records the current head of the migration graph.
    # A conflict here means two branches added a migration from the same parent.
    # Resolve with:  alembic-linear rebase
    #
    c4e6a8b0d2f1

The header is byte-identical on both sides of any merge, so it merges silently
and only the revision line conflicts. Whoever hits that conflict is told what
it means and how to fix it, in place, without reading docs.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import AlembicLinearError

__all__ = [
    "HEADER",
    "ConflictSides",
    "parse",
    "parse_conflict",
    "read",
    "render",
    "write",
]

HEADER = (
    "# alembic-linear-migrations\n"
    "# Records the current head of the migration graph.\n"
    "# A conflict here means two branches added a migration from the same parent.\n"
    "# Resolve with:  alembic-linear rebase\n"
    "#\n"
)

_CONFLICT_START = "<<<<<<<"
_CONFLICT_BASE = "|||||||"
_CONFLICT_SEP = "======="
_CONFLICT_END = ">>>>>>>"


class ConflictSides(NamedTuple):
    """The two revisions git found on either side of a ``head.txt`` conflict.

    ``head`` is the ``<<<<<<< HEAD`` side and ``other`` is the ``>>>>>>>``
    side, named after the markers rather than after "ours"/"theirs" -- which
    side is whose depends on whether git is merging or rebasing, and that
    mapping belongs to :mod:`alembic_linear_migrations.rebase`.
    """

    head: str
    other: str


def render(revision: str) -> str:
    """Build the full file content recording ``revision`` as the head."""
    return f"{HEADER}{revision}\n"


def _content_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _has_conflict_markers(text: str) -> bool:
    return any(line.startswith(_CONFLICT_START) for line in text.splitlines()) and any(
        line.startswith(_CONFLICT_END) for line in text.splitlines()
    )


def _one_revision(lines: list[str], path: Path, side: str = "") -> str:
    where = f"{path}{side}"
    if not lines:
        raise AlembicLinearError(
            f"{where} records no revision. Run:  alembic-linear update"
        )
    if len(lines) > 1:
        joined = ", ".join(lines)
        raise AlembicLinearError(
            f"{where} records more than one revision ({joined}).\n"
            f"It must hold exactly one. Run:  alembic-linear update"
        )
    return lines[0]


def parse_conflict(text: str, path: Path) -> ConflictSides | None:
    """Extract both sides of an unresolved conflict, or ``None`` if resolved.

    Handles the ``merge``, ``diff3``, and ``zdiff3`` conflict styles; the
    common-ancestor section that ``diff3`` adds is skipped.
    """
    if not _has_conflict_markers(text):
        return None

    head_lines: list[str] = []
    other_lines: list[str] = []
    # Outside any conflict block until proven otherwise; `base` marks the
    # diff3 ancestor section, whose content belongs to neither side.
    section = "outside"
    for line in text.splitlines():
        if line.startswith(_CONFLICT_START):
            section = "head"
        elif line.startswith(_CONFLICT_BASE):
            section = "base"
        elif line.startswith(_CONFLICT_SEP):
            section = "other"
        elif line.startswith(_CONFLICT_END):
            section = "outside"
        elif section == "head":
            head_lines.append(line)
        elif section == "other":
            other_lines.append(line)

    return ConflictSides(
        head=_one_revision(_content_lines("\n".join(head_lines)), path, " (HEAD side)"),
        other=_one_revision(
            _content_lines("\n".join(other_lines)), path, " (incoming side)"
        ),
    )


def parse(text: str, path: Path) -> str:
    """Extract the recorded revision from ``head.txt`` content."""
    if _has_conflict_markers(text):
        raise AlembicLinearError(
            f"{path} has unresolved conflict markers.\n"
            f"Two branches added a migration from the same parent. "
            f"Run:  alembic-linear rebase"
        )
    return _one_revision(_content_lines(text), path)


def read(path: Path) -> str:
    """Read the revision recorded in ``head.txt``."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AlembicLinearError(
            f"{path} does not exist. Create it with:  alembic-linear update"
        ) from None
    return parse(text, path)


def write(path: Path, revision: str) -> bool:
    """Record ``revision`` in ``head.txt``. Returns True if the file changed."""
    content = render(revision)
    existing: str | None
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    if existing == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True
