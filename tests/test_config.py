"""Config discovery and script-location resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from alembic_linear_migrations import AlembicLinearError
from alembic_linear_migrations.config import discover


def test_explicit_config_needs_no_working_directory(project):
    found = discover(str(project.ini))
    assert found.head_file == project.head_file


def test_explicit_config_must_exist(tmp_path):
    with pytest.raises(AlembicLinearError, match="No such config file"):
        discover(str(tmp_path / "nope.ini"))


def test_discovery_searches_upward_from_the_working_directory(project, in_dir):
    nested = project.root / "src" / "deep"
    nested.mkdir(parents=True)
    os.chdir(nested)
    assert discover().config_path == project.ini


def test_discovery_can_be_anchored_away_from_the_working_directory(
    project, tmp_path, in_dir
):
    os.chdir(tmp_path)
    assert discover(start=project.versions).config_path == project.ini


def test_discovery_names_the_flag_when_nothing_is_found(tmp_path, in_dir):
    outside = tmp_path / "empty"
    outside.mkdir()
    os.chdir(outside)
    with pytest.raises(AlembicLinearError, match="--config"):
        discover()


def test_head_file_sits_next_to_env_py_not_inside_versions(project):
    found = discover(str(project.ini))
    assert found.head_file.parent == project.script_dir
    assert (found.head_file.parent / "env.py").exists()
    assert not (project.versions / "head.txt").exists()


def test_relative_script_location_resolves_against_the_ini_not_the_cwd(
    make_project, tmp_path, in_dir
):
    """Alembic anchors a bare relative path to the cwd; we anchor it to the ini.

    A pre-commit hook runs from the repository root and a post_write_hook runs
    from wherever the developer was, so cwd cannot be relied on.
    """
    project = make_project(script_location="migrations")
    project.add_chain("aaaa", "bbbb")
    os.chdir(tmp_path)

    found = discover(str(project.ini))

    assert found.script_dir == project.script_dir.resolve()
    # Reading the revisions is the part that actually needs the anchoring:
    # resolving script_location alone would not catch a lazily-loaded graph.
    assert found.heads(found.load_script()) == ("bbbb",)


def test_a_migration_importing_app_code_explains_itself(make_project):
    """Alembic executes each migration to read its ids, so its imports must resolve.

    This is the pre-commit failure mode: the hook's environment has alembic but
    not the application, so the message has to name the fix rather than dump a
    ModuleNotFoundError traceback.
    """
    project = make_project()
    project.add_revision("aaaa", None)
    (project.versions / "bbbb_app.py").write_text(
        "from myapp.models import StatusEnum\n"
        "revision = 'bbbb'\n"
        "down_revision = 'aaaa'\n"
    )

    with pytest.raises(AlembicLinearError) as exc:
        discover(str(project.ini)).load_script()

    message = str(exc.value)
    assert "ModuleNotFoundError" in message
    assert "language: system" in message


def test_bad_script_location_is_reported_without_a_traceback(make_project):
    project = make_project(script_location="%(here)s/does-not-exist")
    with pytest.raises(AlembicLinearError, match="Alembic could not read"):
        discover(str(project.ini))


def test_discovery_leaves_the_working_directory_alone(project, in_dir):
    """Reading the graph borrows the config file's directory; it must give it back."""
    before = Path.cwd()
    discover(str(project.ini)).load_script()
    assert Path.cwd() == before
