"""rebase against real git merge, rebase, and cherry-pick conflicts.

These build actual repositories and let git produce the conflicts, because the
whole point of the command is that git labels the two sides differently
depending on the operation. A hand-written fixture would encode the same
assumption the code makes, and prove nothing.
"""

from __future__ import annotations

import pytest

from alembic_linear_migrations import AlembicLinearError, head
from alembic_linear_migrations.config import discover
from alembic_linear_migrations.rebase import _rewrite_down_revision, rebase

from .conftest import AlembicProject


def _read_down_revision(project: AlembicProject, revision: str) -> str:
    text = next(project.versions.glob(f"{revision}_*.py")).read_text()
    line = next(li for li in text.splitlines() if li.startswith("down_revision"))
    return line.split("=", 1)[1].strip()


@pytest.fixture
def diverged(make_project, git):
    """Two branches that each add a migration from the same parent.

    ``feature`` adds the migrations in ``ours``; ``main`` adds ``mmmm``. The
    operation runs from ``feature``, which is where a developer would be.
    """

    def _diverged(operation: str, ours=("ffff",)):
        project = make_project()
        root = project.root
        git("init", "-b", "main", "-q", ".", cwd=root)

        project.add_revision("aaaa", None, message="base")
        project.write_head("aaaa")
        git("add", "-A", cwd=root)
        git("commit", "-qm", "base", cwd=root)

        git("checkout", "-qb", "feature", cwd=root)
        project.add_chain(*ours, down="aaaa")
        project.write_head(ours[-1])
        git("add", "-A", cwd=root)
        git("commit", "-qm", "feature migrations", cwd=root)
        feature_sha = git("rev-parse", "HEAD", cwd=root).strip()

        git("checkout", "-q", "main", cwd=root)
        project.add_revision("mmmm", "aaaa", message="main")
        project.write_head("mmmm")
        git("add", "-A", cwd=root)
        git("commit", "-qm", "main migration", cwd=root)

        if operation == "cherry-pick":
            # Replaying feature's commit onto main, standing on main.
            git("cherry-pick", feature_sha, cwd=root)
        else:
            git("checkout", "-q", "feature", cwd=root)
            git(operation, "main", cwd=root)

        return project

    return _diverged


def test_the_two_migration_files_themselves_merge_cleanly(diverged):
    """The premise: separate files never collide, so only head.txt can."""
    project = diverged("merge")
    assert (project.versions / "ffff_ffff.py").exists()
    assert (project.versions / "mmmm_main.py").exists()
    assert "<<<<<<<" in project.head_file.read_text()


@pytest.mark.parametrize("operation", ["merge", "rebase", "cherry-pick"])
def test_our_migration_is_re_pointed_onto_theirs(diverged, operation):
    """Ours is always ffff, however git happened to label the two sides."""
    project = diverged(operation)
    found = discover(str(project.ini))

    result = rebase(found)

    assert result.ours == "ffff"
    assert result.theirs == "mmmm"
    assert _read_down_revision(project, "ffff") == "'mmmm'"
    assert head.read(project.head_file) == "ffff"


@pytest.mark.parametrize("operation", ["merge", "rebase", "cherry-pick"])
def test_the_graph_has_one_head_afterwards(diverged, operation):
    project = diverged(operation)
    found = discover(str(project.ini))
    rebase(found)

    assert found.heads(found.load_script()) == ("ffff",)


def test_only_the_base_of_a_multi_migration_branch_moves(diverged):
    """A branch may add several migrations; only the bottom one is re-pointed."""
    project = diverged("rebase", ours=("ffff", "gggg", "hhhh"))
    found = discover(str(project.ini))

    result = rebase(found)

    assert result.rebased == "ffff"
    assert _read_down_revision(project, "ffff") == "'mmmm'"
    assert _read_down_revision(project, "gggg") == "'ffff'"
    assert _read_down_revision(project, "hhhh") == "'gggg'"
    assert head.read(project.head_file) == "hhhh"
    assert found.heads(found.load_script()) == ("hhhh",)


def test_a_same_size_rewrite_survives_cached_bytecode(diverged):
    """Both signals CPython uses to invalidate a .pyc miss here.

    A revision id has a fixed width, so swapping one for another leaves the
    file size untouched, and the verification re-read happens in the same
    second as the write. Without dropping the cached bytecode, alembic re-reads
    the pre-rebase graph and the command fails claiming two heads remain.
    """
    project = diverged("merge")
    found = discover(str(project.ini))
    found.load_script()  # reads every revision, so the .pyc gets written
    path = project.versions / "ffff_ffff.py"
    size_before = path.stat().st_size

    rebase(found)

    assert path.stat().st_size == size_before, "rewrite should be size-neutral"
    assert found.heads(found.load_script()) == ("ffff",)


def test_the_rewrite_keeps_the_type_annotation(diverged):
    project = diverged("merge")
    rebase(discover(str(project.ini)))

    text = (project.versions / "ffff_ffff.py").read_text()
    assert "down_revision: Union[str, None] = 'mmmm'" in text


def test_the_result_reports_what_it_changed(diverged):
    project = diverged("merge")
    result = rebase(discover(str(project.ini)))

    summary = result.summary()
    assert "aaaa -> mmmm" in summary
    assert "not their content" in summary


def test_onto_resolves_a_conflict_with_no_git_at_all(make_project):
    """--onto is the escape hatch: it needs no repository."""
    project = make_project()
    project.add_revision("aaaa", None)
    project.add_revision("ffff", "aaaa")
    project.add_revision("mmmm", "aaaa")
    project.write_head("ffff")

    result = rebase(discover(str(project.ini)), onto="mmmm")

    assert (result.ours, result.theirs) == ("ffff", "mmmm")
    assert head.read(project.head_file) == "ffff"


def test_onto_overrides_what_git_would_have_inferred(diverged):
    """Naming ffff as the target inverts the roles the merge implied."""
    project = diverged("merge")
    result = rebase(discover(str(project.ini)), onto="ffff")

    assert (result.ours, result.theirs) == ("mmmm", "ffff")
    assert _read_down_revision(project, "mmmm") == "'ffff'"
    assert head.read(project.head_file) == "mmmm"


def test_onto_must_name_one_of_the_heads(diverged):
    project = diverged("merge")
    with pytest.raises(AlembicLinearError, match="not one of the two heads"):
        rebase(discover(str(project.ini)), onto="aaaa")


def test_a_conflict_outside_any_git_operation_asks_for_onto(diverged, git):
    project = diverged("merge")
    git("merge", "--abort", cwd=project.root)
    # Restore the conflicted file without the merge state that explains it.
    project.head_file.write_text(
        head.HEADER + "<<<<<<< HEAD\nffff\n=======\nmmmm\n>>>>>>> main\n"
    )
    project.add_revision("mmmm", "aaaa", message="main")

    with pytest.raises(AlembicLinearError) as exc:
        rebase(discover(str(project.ini)))

    assert "--onto ffff" in str(exc.value)
    assert "--onto mmmm" in str(exc.value)


def test_two_heads_without_conflict_markers_asks_for_onto(make_project):
    project = make_project()
    project.add_revision("aaaa", None)
    project.add_revision("ffff", "aaaa")
    project.add_revision("mmmm", "aaaa")
    project.write_head("ffff")

    with pytest.raises(AlembicLinearError, match="no conflict markers"):
        rebase(discover(str(project.ini)))


def test_two_heads_without_a_head_file_asks_for_onto(make_project):
    """A missing head.txt is a clean --onto prompt, not a FileNotFoundError."""
    project = make_project()
    project.add_revision("aaaa", None)
    project.add_revision("ffff", "aaaa")
    project.add_revision("mmmm", "aaaa")
    assert not project.head_file.exists()

    with pytest.raises(AlembicLinearError, match="--onto"):
        rebase(discover(str(project.ini)))


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("down_revision = 'aaaa'", "down_revision = 'mmmm'"),
        ('down_revision = "aaaa"', "down_revision = 'mmmm'"),
        (
            "down_revision: Union[str, None] = 'aaaa'",
            "down_revision: Union[str, None] = 'mmmm'",
        ),
        ("down_revision: str | None = 'aaaa'", "down_revision: str | None = 'mmmm'"),
        ("down_revision  =  'aaaa'", "down_revision  =  'mmmm'"),
        ("down_revision = 'aaaa'  # keep", "down_revision = 'mmmm'  # keep"),
        ("down_revision = None", "down_revision = 'mmmm'"),
    ],
    ids=["bare", "double-quoted", "annotated", "pep604", "spaced", "comment", "none"],
)
def test_the_rewrite_handles_the_shapes_alembic_writes(tmp_path, original, expected):
    path = tmp_path / "rev.py"
    path.write_text(f"revision = 'ffff'\n{original}\ndepends_on = None\n")

    _rewrite_down_revision(path, "mmmm")

    assert path.read_text().splitlines()[1] == expected


def test_the_rewrite_refuses_a_file_with_no_down_revision(tmp_path):
    path = tmp_path / "rev.py"
    path.write_text("revision = 'ffff'\n")

    with pytest.raises(AlembicLinearError, match="Could not find a module-level"):
        _rewrite_down_revision(path, "mmmm")


def test_the_rewrite_refuses_an_ambiguous_file(tmp_path):
    """Two assignments mean the intent is unclear; guessing would corrupt the graph."""
    path = tmp_path / "rev.py"
    path.write_text("down_revision = 'aaaa'\ndown_revision = 'bbbb'\n")

    with pytest.raises(AlembicLinearError, match="expected exactly one"):
        _rewrite_down_revision(path, "mmmm")


@pytest.mark.parametrize("parents", ["['aaaa', 'bbbb']", "('aaaa', 'bbbb')"])
def test_a_merge_revision_is_reported_as_out_of_scope(make_project, parents):
    """Alembic accepts a list or a tuple of parents; both mean a branched history."""
    project = make_project()
    project.add_chain("aaaa", "bbbb")
    merge = project.versions / "merge_rev.py"
    merge.write_text(
        f"revision = 'mergerev'\ndown_revision = {parents}\n"
        f"branch_labels = None\ndepends_on = None\n"
    )
    project.add_revision("ffff", "bbbb")

    with pytest.raises(AlembicLinearError, match="is a merge revision"):
        rebase(discover(str(project.ini)), onto="ffff")


def test_a_single_head_has_nothing_to_rebase(project):
    with pytest.raises(AlembicLinearError, match="already has one head"):
        rebase(discover(str(project.ini)))


def test_three_heads_is_reported_as_out_of_scope(project):
    for revision in ("d1d1", "d2d2", "d3d3"):
        project.add_revision(revision, "cccc")

    with pytest.raises(AlembicLinearError, match="3 heads"):
        rebase(discover(str(project.ini)))


def test_a_stale_side_in_head_txt_is_refused(diverged):
    """head.txt naming a revision that is not a head means something else broke."""
    project = diverged("merge")
    project.head_file.write_text(
        head.HEADER + "<<<<<<< HEAD\nzzzz\n=======\nmmmm\n>>>>>>> main\n"
    )

    with pytest.raises(AlembicLinearError, match="not a head of the graph"):
        rebase(discover(str(project.ini)))


def test_a_failed_rebase_restores_every_file_it_touched(diverged, monkeypatch):
    project = diverged("merge")
    found = discover(str(project.ini))
    before_script = (project.versions / "ffff_ffff.py").read_text()
    before_head = project.head_file.read_text()

    import alembic_linear_migrations.rebase as rebase_module

    def _broken(project_, expected):
        raise AlembicLinearError("graph still has two heads")

    monkeypatch.setattr(rebase_module, "_assert_single_head", _broken)

    with pytest.raises(AlembicLinearError, match="two heads"):
        rebase(found)

    assert (project.versions / "ffff_ffff.py").read_text() == before_script
    assert project.head_file.read_text() == before_head
