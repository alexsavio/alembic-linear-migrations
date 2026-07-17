"""Detect which git operation is in progress, if any.

Only enough git to answer one question: when ``head.txt`` conflicts, which
side did the person running the command write? Git's own ``HEAD``/incoming
labelling inverts between merging and replaying, and getting that backwards
re-points the wrong migration.
"""

from __future__ import annotations

import enum
import subprocess
from pathlib import Path

__all__ = ["GitState", "detect"]


class GitState(enum.Enum):
    """The git operation in progress, named for how it labels the two sides."""

    #: ``git merge``: HEAD is the branch the developer is on, so HEAD is ours.
    MERGE = "merge"

    #: ``git rebase``: HEAD is the upstream being replayed onto, and the
    #: incoming side carries the developer's own commit. Sides are inverted.
    REBASE = "rebase"

    #: ``git cherry-pick``: like a rebase, HEAD is the established base and the
    #: incoming side is the commit being replayed on top of it.
    CHERRY_PICK = "cherry-pick"

    #: No operation in progress, or not a git repository at all.
    NONE = "none"

    @property
    def head_side_is_ours(self) -> bool:
        return self is GitState.MERGE

    @property
    def description(self) -> str:
        return {
            GitState.MERGE: "a merge is in progress",
            GitState.REBASE: "a rebase is in progress",
            GitState.CHERRY_PICK: "a cherry-pick is in progress",
            GitState.NONE: "no merge, rebase, or cherry-pick is in progress",
        }[self]


def _git_dir(cwd: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    path = completed.stdout.strip()
    return Path(path) if path else None


def detect(cwd: Path) -> GitState:
    """Report the git operation in progress in the repository holding ``cwd``."""
    git_dir = _git_dir(cwd)
    if git_dir is None:
        return GitState.NONE
    if (git_dir / "MERGE_HEAD").exists():
        return GitState.MERGE
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return GitState.REBASE
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return GitState.CHERRY_PICK
    return GitState.NONE
