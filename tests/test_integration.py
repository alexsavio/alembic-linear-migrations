"""End-to-end wiring, driven through the real alembic and pre-commit CLIs.

These are the tests that would catch the two triggers being wired wrong, which
unit tests cannot: the post_write_hook only proves itself when alembic resolves
the entry point and spawns it, and the pre-commit hook only proves itself when
pre-commit builds an isolated environment from this repository.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from alembic_linear_migrations import head

REPO_ROOT = Path(__file__).resolve().parent.parent

HOOK_INI_BLOCK = """
hooks = alembic_linear
alembic_linear.type = console_scripts
alembic_linear.entrypoint = alembic-linear-update
"""


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, check=False
    )


@pytest.fixture
def alembic_app(tmp_path: Path) -> Path:
    """A project scaffolded by `alembic init`, wired to the post_write_hook."""
    root = tmp_path / "app"
    root.mkdir()

    created = _run(sys.executable, "-m", "alembic", "init", "migrations", cwd=root)
    if created.returncode != 0:  # pragma: no cover
        pytest.skip(f"alembic init failed: {created.stderr}")

    ini = root / "alembic.ini"
    ini.write_text(
        ini.read_text().replace(
            "[post_write_hooks]", "[post_write_hooks]" + HOOK_INI_BLOCK, 1
        )
    )
    return root


def test_post_write_hook_fires_on_alembic_revision(alembic_app):
    """The console_scripts hook type, exercised by alembic itself.

    head.txt exists only if alembic resolved the entry point and ran it, which
    is the whole claim. Alembic's own progress wording is not part of it and
    differs across versions, so it is not asserted on.
    """
    created = _run(
        sys.executable, "-m", "alembic", "revision", "-m", "first", cwd=alembic_app
    )
    assert created.returncode == 0, created.stderr

    head_file = alembic_app / "migrations" / "head.txt"
    assert head_file.exists(), created.stdout + created.stderr
    revision = next((alembic_app / "migrations" / "versions").glob("*.py")).name[:12]
    assert head.read(head_file) == revision


def test_post_write_hook_moves_the_head_on_each_revision(alembic_app):
    _run(sys.executable, "-m", "alembic", "revision", "-m", "first", cwd=alembic_app)
    first = head.read(alembic_app / "migrations" / "head.txt")

    _run(sys.executable, "-m", "alembic", "revision", "-m", "second", cwd=alembic_app)
    second = head.read(alembic_app / "migrations" / "head.txt")

    assert first != second
    history = _run(sys.executable, "-m", "alembic", "history", cwd=alembic_app).stdout
    assert f"{first} -> {second} (head)" in history


def test_post_write_hook_leaves_head_txt_out_of_the_versions_directory(alembic_app):
    """Alembic scans versions/; a stray non-.py file there is a hazard."""
    _run(sys.executable, "-m", "alembic", "revision", "-m", "first", cwd=alembic_app)

    assert (alembic_app / "migrations" / "head.txt").exists()
    assert not (alembic_app / "migrations" / "versions" / "head.txt").exists()
    listed = _run(sys.executable, "-m", "alembic", "history", cwd=alembic_app)
    assert listed.returncode == 0, listed.stderr


@pytest.mark.slow
def test_pre_commit_hook_blocks_a_commit_that_leaves_head_txt_stale(alembic_app, git):
    """The gap the post_write_hook cannot cover: a hand-written migration."""
    if shutil.which("pre-commit") is None:  # pragma: no cover
        pytest.skip("pre-commit is not installed")

    _run(sys.executable, "-m", "alembic", "revision", "-m", "first", cwd=alembic_app)

    (alembic_app / ".pre-commit-config.yaml").write_text(
        f"repos:\n"
        f"  - repo: {REPO_ROOT}\n"
        f"    rev: {git('rev-parse', 'HEAD', cwd=REPO_ROOT).strip()}\n"
        f"    hooks:\n"
        f"      - id: alembic-linear\n"
    )
    git("init", "-b", "main", "-q", ".", cwd=alembic_app)
    git("add", "-A", cwd=alembic_app)
    git("commit", "-qm", "initial", cwd=alembic_app)

    # A migration written by hand never goes through the CLI, so no hook fired
    # and head.txt still names the previous revision.
    first = head.read(alembic_app / "migrations" / "head.txt")
    (alembic_app / "migrations" / "versions" / "handwritten.py").write_text(
        f"revision = 'handwritten1'\ndown_revision = {first!r}\n"
        f"branch_labels = None\ndepends_on = None\n\n"
        f"def upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n"
    )
    git("add", "-A", cwd=alembic_app)

    blocked = _run("pre-commit", "run", "--all-files", cwd=alembic_app)

    assert blocked.returncode != 0, blocked.stdout
    assert head.read(alembic_app / "migrations" / "head.txt") == "handwritten1"

    passes = _run("pre-commit", "run", "--all-files", cwd=alembic_app)
    assert passes.returncode == 0, passes.stdout
