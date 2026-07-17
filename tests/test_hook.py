"""The post_write_hook entry point, called the way alembic calls it."""

from __future__ import annotations

import os

from alembic_linear_migrations import head
from alembic_linear_migrations.hook import main


def test_hook_records_the_head_of_a_freshly_written_revision(project, tmp_path, in_dir):
    """Alembic passes the path of the script it just wrote as argv[1]."""
    os.chdir(tmp_path)  # alembic ran from somewhere else entirely
    written = project.add_revision("dddd", "cccc", message="new")

    assert main([str(written)]) == 0
    assert head.read(project.head_file) == "dddd"


def test_hook_finds_the_project_from_the_revision_path_not_the_cwd(
    project, tmp_path, in_dir
):
    os.chdir(tmp_path)
    written = project.add_revision("dddd", "cccc")

    main([str(written)])

    assert project.head_file.exists()


def test_hook_falls_back_to_the_cwd_when_given_no_arguments(project, in_dir):
    os.chdir(project.root)
    project.add_revision("dddd", "cccc")

    assert main([]) == 0
    assert head.read(project.head_file) == "dddd"


def test_hook_reports_errors_on_stderr_without_a_traceback(tmp_path, capsys, in_dir):
    os.chdir(tmp_path)

    assert main([]) == 1

    captured = capsys.readouterr()
    assert captured.err.startswith("alembic-linear: ")
    assert "Traceback" not in captured.err


def test_hook_is_quiet_when_the_head_file_is_already_current(project, in_dir):
    os.chdir(project.root)

    assert main([]) == 0
    assert main([]) == 0


def test_hook_ignores_an_argument_that_is_not_a_file(project, in_dir):
    os.chdir(project.root)
    project.add_revision("dddd", "cccc")

    assert main(["--some-option-alembic-passed-through"]) == 0
    assert head.read(project.head_file) == "dddd"
