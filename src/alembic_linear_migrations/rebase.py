"""Resolve a ``head.txt`` conflict by re-pointing one branch onto the other.

After a conflict both migrations are present, so the graph has exactly two
heads. One of them is *ours* -- the one the developer running the command
wrote -- and its chain gets re-pointed to sit on top of *theirs*.

Which side is ours is the part hand-rolled scripts get wrong. Git labels the
sides of a conflict ``HEAD`` and incoming, but the meaning inverts: merging
puts our own work on the ``HEAD`` side, while rebasing checks out the upstream
first and replays our commit as the incoming side.
"""

from __future__ import annotations

import contextlib
import importlib.util
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from alembic.script import Script, ScriptDirectory

from . import AlembicLinearError
from . import head as head_file
from .commands import single_head
from .config import Project
from .gitstate import GitState, detect

__all__ = ["RebaseResult", "rebase"]

# Matches the module-level `down_revision` assignment in a migration script,
# with or without a type annotation, capturing the value apart from any
# trailing comment:
#     down_revision = 'abc'
#     down_revision: Union[str, None] = "abc"  # note
_DOWN_REVISION_RE = re.compile(
    r"^(?P<prefix>down_revision\s*(?::[^=\n]+)?=\s*)"
    r"(?P<value>[^#\n]+?)"
    r"(?P<trailing>[ \t]*(?:#.*)?)$",
    re.MULTILINE,
)


class RebaseResult(NamedTuple):
    ours: str
    theirs: str
    rebased: str
    previous_down_revision: str | None
    path: Path

    def summary(self) -> str:
        was = self.previous_down_revision or "<base>"
        return (
            f"Re-pointed {self.rebased} onto {self.theirs}.\n\n"
            f"  {self.path}\n"
            f"    down_revision: {was} -> {self.theirs}\n\n"
            f"  head.txt now records {self.ours}, and the graph has one head.\n\n"
            f"This fixes the ordering of the two migrations, not their content. "
            f"Read them\nboth before staging: if they touch the same table or "
            f"column, running one\nafter the other may still be wrong.\n\n"
            f"  git add {self.path} head.txt"
        )


def _sole_parent(project: Project, revision: Script) -> str | None:
    """The one revision ``revision`` sits on top of, if there is only one.

    Alembic allows ``down_revision`` to be a string, a list, or a tuple. More
    than one entry means a merge revision, which is a deliberately branched
    history and out of scope.
    """
    down = revision.down_revision
    if down is None or isinstance(down, str):
        return down

    parents = tuple(down)
    if len(parents) > 1:
        raise AlembicLinearError(
            f"{project.script_path(revision).name} is a merge revision: its "
            f"down_revision names {len(parents)} parents.\n"
            f"alembic-linear-migrations only models linear histories, so this "
            f"one has to be resolved by hand."
        )
    return parents[0] if parents else None


def _ancestry(project: Project, script: ScriptDirectory, head: str) -> list[str]:
    """Every revision from ``head`` down to its base, nearest first."""
    chain: list[str] = []
    current: str | None = head
    seen: set[str] = set()
    while current is not None:
        if current in seen:  # pragma: no cover - alembic rejects cycles first
            raise AlembicLinearError(f"The migration graph has a cycle at {current}.")
        seen.add(current)
        revision = script.get_revision(current)
        chain.append(revision.revision)
        current = _sole_parent(project, revision)
    return chain


def _branch_point(ours_chain: Sequence[str], theirs_chain: Sequence[str]) -> str | None:
    theirs = set(theirs_chain)
    for revision in ours_chain:
        if revision in theirs:
            return revision
    return None


def _base_of_our_branch(ours_chain: Sequence[str], theirs_chain: Sequence[str]) -> str:
    """The oldest revision that is ours alone -- the one to re-point.

    A branch may add several migrations. Only the bottom one points at the
    shared parent, so that is the single link to move; the rest of the chain
    rides along.
    """
    shared = _branch_point(ours_chain, theirs_chain)
    if shared is None:
        # The two graphs have no revision in common, so our chain runs all the
        # way to its own root and that root is the link to move.
        return ours_chain[-1]
    index = ours_chain.index(shared)
    if index == 0:  # pragma: no cover - such a revision would not be a head
        raise AlembicLinearError(
            f"{shared} is on both branches and is also a head; "
            f"the graph is inconsistent."
        )
    return ours_chain[index - 1]


def _drop_cached_bytecode(path: Path) -> None:
    """Discard any ``.pyc`` compiled from ``path``.

    CPython decides a cached ``.pyc`` is still valid by comparing the source's
    size and its mtime truncated to whole seconds. Re-pointing a down_revision
    swaps one revision id for another of the same width, and the re-read
    happens milliseconds later, so both signals miss and alembic imports the
    stale bytecode -- reporting the graph as it was before the rewrite.
    """
    with contextlib.suppress(NotImplementedError, ValueError, OSError):
        Path(importlib.util.cache_from_source(str(path))).unlink()
    importlib.invalidate_caches()


def _rewrite_down_revision(path: Path, new_down: str) -> str:
    """Point ``path``'s down_revision at ``new_down``; return the old content."""
    original = path.read_text(encoding="utf-8")
    matches = _DOWN_REVISION_RE.findall(original)
    if not matches:
        raise AlembicLinearError(
            f"Could not find a module-level down_revision assignment in {path}."
        )
    if len(matches) > 1:
        raise AlembicLinearError(
            f"Found {len(matches)} down_revision assignments in {path}; "
            f"expected exactly one."
        )

    def substitute(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{new_down!r}{match.group('trailing')}"

    path.write_text(
        _DOWN_REVISION_RE.sub(substitute, original, count=1), encoding="utf-8"
    )
    _drop_cached_bytecode(path)
    return original


def _sides(project: Project, onto: str | None, heads: Sequence[str]) -> tuple[str, str]:
    """Work out which head is ours and which is theirs."""
    if onto is not None:
        if onto not in heads:
            listed = ", ".join(heads)
            raise AlembicLinearError(
                f"--onto {onto} is not one of the two heads ({listed})."
            )
        theirs = onto
        ours = next(head for head in heads if head != onto)
        return ours, theirs

    state = detect(project.root)
    # A missing head.txt carries no sides to read, exactly like a resolved one;
    # both land on the --onto prompt below rather than a FileNotFoundError.
    try:
        head_text = project.head_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        head_text = ""
    conflict = head_file.parse_conflict(head_text, project.head_file)

    if conflict is None:
        raise AlembicLinearError(
            f"The graph has two heads but {project.head_file} has no conflict "
            f"markers,\nso there is nothing to read the two sides from "
            f"({state.description}).\n\n"
            f"Name the head to rebase onto -- the other branch's revision:\n"
            f"  alembic-linear rebase --onto {heads[0]}\n"
            f"  alembic-linear rebase --onto {heads[1]}"
        )

    if state is GitState.NONE:
        raise AlembicLinearError(
            f"{project.head_file} has conflict markers, but "
            f"{state.description},\nso which side is yours cannot be inferred.\n\n"
            f"Name the head to rebase onto -- the other branch's revision:\n"
            f"  alembic-linear rebase --onto {conflict.head}\n"
            f"  alembic-linear rebase --onto {conflict.other}"
        )

    for side in conflict:
        if side not in heads:
            listed = ", ".join(heads)
            raise AlembicLinearError(
                f"{project.head_file} records {side} on one side of the "
                f"conflict, but\nthat is not a head of the graph ({listed}). "
                f"Recreate the conflict or\nname the sides with --onto."
            )

    if state.head_side_is_ours:
        return conflict.head, conflict.other
    return conflict.other, conflict.head


def rebase(project: Project, onto: str | None = None) -> RebaseResult:
    """Re-point our branch's migrations onto the other branch's head."""
    script = project.load_script()
    heads = project.heads(script)

    if len(heads) == 1:
        raise AlembicLinearError(
            f"The graph already has one head ({heads[0]}); there is nothing to "
            f"rebase.\nIf head.txt is stale, run:  alembic-linear update"
        )
    if len(heads) != 2:
        # single_head() words the zero-head and many-head cases already.
        single_head(project, script)
        raise AlembicLinearError(  # pragma: no cover - single_head always raises
            f"Expected two heads, found {len(heads)}."
        )

    ours, theirs = _sides(project, onto, heads)

    ours_chain = _ancestry(project, script, ours)
    theirs_chain = _ancestry(project, script, theirs)
    rebased = _base_of_our_branch(ours_chain, theirs_chain)

    revision = script.get_revision(rebased)
    path = project.script_path(revision)
    previous_down = _sole_parent(project, revision)

    original_script = _rewrite_down_revision(path, theirs)
    original_head = (
        project.head_file.read_text(encoding="utf-8")
        if project.head_file.exists()
        else None
    )
    head_file.write(project.head_file, ours)

    try:
        _assert_single_head(project, ours)
    except AlembicLinearError:
        path.write_text(original_script, encoding="utf-8")
        _drop_cached_bytecode(path)
        if original_head is None:
            project.head_file.unlink()
        else:
            project.head_file.write_text(original_head, encoding="utf-8")
        raise

    return RebaseResult(
        ours=ours,
        theirs=theirs,
        rebased=rebased,
        previous_down_revision=previous_down,
        path=path,
    )


def _assert_single_head(project: Project, expected: str) -> None:
    """Verify the rewrite produced the linear graph it promised."""
    script = project.load_script()
    heads = project.heads(script)
    if len(heads) != 1 or heads[0] != expected:
        found = ", ".join(heads) if heads else "none"
        raise AlembicLinearError(
            f"Rebase would have left the graph with heads: {found} "
            f"(expected only {expected}).\nNo files were changed."
        )
