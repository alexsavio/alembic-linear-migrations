"""update and check against linear, two-head, stale, and hand-written projects."""

from __future__ import annotations

import pytest

from alembic_linear_migrations import AlembicLinearError, head
from alembic_linear_migrations.commands import check, update
from alembic_linear_migrations.config import discover


def test_update_records_the_head_of_a_linear_graph(project):
    found = discover(str(project.ini))
    project.head_file.unlink()

    assert update(found) is True
    assert head.read(project.head_file) == "cccc"


def test_update_is_idempotent(project):
    found = discover(str(project.ini))
    assert update(found) is False


def test_update_rewrites_a_stale_head_file(project):
    project.write_head("aaaa")
    found = discover(str(project.ini))

    assert update(found) is True
    assert head.read(project.head_file) == "cccc"


def test_update_picks_up_a_hand_written_migration(project):
    """A migration added by hand never went through the CLI, so no hook fired."""
    project.add_revision("dddd", "cccc", message="by hand")
    found = discover(str(project.ini))

    assert update(found) is True
    assert head.read(project.head_file) == "dddd"


def test_update_reads_migrations_without_type_annotations(make_project):
    project = make_project()
    project.add_revision("aaaa", None, annotated=False)
    project.add_revision("bbbb", "aaaa", annotated=False)
    found = discover(str(project.ini))

    assert update(found) is True
    assert head.read(project.head_file) == "bbbb"


def test_update_writes_the_full_header(project):
    project.head_file.unlink()
    update(discover(str(project.ini)))

    text = project.head_file.read_text()
    assert text.startswith("# alembic-linear-migrations")
    assert "alembic-linear rebase" in text


def test_check_passes_on_a_linear_graph_with_a_current_head_file(project):
    check(discover(str(project.ini)))


def test_check_reports_a_stale_head_file_with_both_revisions(project):
    project.write_head("aaaa")
    with pytest.raises(AlembicLinearError) as exc:
        check(discover(str(project.ini)))

    message = str(exc.value)
    assert "stale" in message
    assert "recorded: aaaa" in message
    assert "actual:   cccc" in message


def test_check_reports_a_missing_head_file(project):
    project.head_file.unlink()
    with pytest.raises(AlembicLinearError, match="does not exist"):
        check(discover(str(project.ini)))


def test_two_heads_are_named_with_their_filenames_and_point_at_rebase(project):
    project.add_revision("d1d1", "cccc", message="add users")
    project.add_revision("d2d2", "cccc", message="add orders")

    with pytest.raises(AlembicLinearError) as exc:
        check(discover(str(project.ini)))

    message = str(exc.value)
    assert "2 heads" in message
    assert "d1d1_add_users.py" in message
    assert "d2d2_add_orders.py" in message
    assert "alembic-linear rebase" in message


def test_two_heads_says_branch_labels_are_out_of_scope(project):
    project.add_revision("d1d1", "cccc")
    project.add_revision("d2d2", "cccc")

    with pytest.raises(AlembicLinearError, match="only models linear histories"):
        update(discover(str(project.ini)))


def test_a_project_with_no_migrations_is_reported_plainly(make_project):
    project = make_project()
    with pytest.raises(AlembicLinearError, match="No migrations found"):
        update(discover(str(project.ini)))
