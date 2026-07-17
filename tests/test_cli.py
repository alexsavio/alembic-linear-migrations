"""CLI argument handling and exit codes."""

from __future__ import annotations

import os

import pytest

from alembic_linear_migrations import head
from alembic_linear_migrations.cli import main


def test_update_exits_zero_and_records_the_head(project, capsys):
    project.head_file.unlink()

    assert main(["update", "-c", str(project.ini)]) == 0

    assert head.read(project.head_file) == "cccc"
    assert "Updated" in capsys.readouterr().out


def test_update_alone_does_not_fail_on_change(project):
    project.write_head("aaaa")
    assert main(["update", "-c", str(project.ini)]) == 0


def test_update_with_exit_on_change_fails_when_it_rewrites(project):
    """What makes the pre-commit hook block a commit."""
    project.write_head("aaaa")

    assert main(["update", "--exit-on-change", "-c", str(project.ini)]) == 1
    assert head.read(project.head_file) == "cccc"


def test_update_with_exit_on_change_passes_when_already_current(project):
    assert main(["update", "--exit-on-change", "-c", str(project.ini)]) == 0


def test_check_exits_zero_when_current(project):
    assert main(["check", "-c", str(project.ini)]) == 0


def test_check_exits_one_when_stale(project, capsys):
    project.write_head("aaaa")

    assert main(["check", "-c", str(project.ini)]) == 1
    assert "stale" in capsys.readouterr().err


def test_check_does_not_rewrite_the_file(project):
    """check is read-only, so CI cannot mask a stale file by fixing it."""
    project.write_head("aaaa")
    main(["check", "-c", str(project.ini)])

    assert head.read(project.head_file) == "aaaa"


def test_errors_are_printed_without_a_traceback(project, capsys):
    project.head_file.unlink()

    assert main(["check", "-c", str(project.ini)]) == 1

    captured = capsys.readouterr()
    assert captured.err.startswith("alembic-linear: ")
    assert "Traceback" not in captured.err


def test_config_before_the_subcommand_is_honoured(project):
    assert main(["-c", str(project.ini), "check"]) == 0


def test_config_after_the_subcommand_is_honoured(project):
    assert main(["check", "-c", str(project.ini)]) == 0


def test_config_omitted_after_subcommand_does_not_clobber_the_global_one(
    project, tmp_path, in_dir
):
    """argparse subparser defaults overwrite parent values unless suppressed."""
    os.chdir(tmp_path)
    assert main(["-c", str(project.ini), "check"]) == 0


def test_no_command_prints_help_and_exits_one(capsys):
    assert main([]) == 1
    assert "usage:" in capsys.readouterr().out


def test_version_is_reported(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip()


def test_rebase_reports_what_it_did(project, capsys):
    project.add_revision("ffff", "cccc")
    project.add_revision("mmmm", "cccc")

    assert main(["rebase", "--onto", "mmmm", "-c", str(project.ini)]) == 0
    assert "Re-pointed ffff onto mmmm" in capsys.readouterr().out
