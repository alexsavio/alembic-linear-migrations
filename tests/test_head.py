"""head.txt rendering, parsing, and conflict handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from alembic_linear_migrations import AlembicLinearError, head


def test_render_ends_with_a_bare_revision_line():
    assert head.render("c4e6a8b0d2f1").endswith("\nc4e6a8b0d2f1\n")


def test_render_round_trips_through_parse():
    assert head.parse(head.render("abc123"), Path("head.txt")) == "abc123"


def test_header_is_all_comments_so_only_the_revision_line_can_conflict():
    header_lines = head.HEADER.strip().splitlines()
    assert all(line.startswith("#") for line in header_lines)


def test_parse_ignores_blank_lines_and_trailing_whitespace():
    assert head.parse("# note\n\n  abc123  \n\n", Path("head.txt")) == "abc123"


def test_parse_rejects_an_empty_file():
    with pytest.raises(AlembicLinearError, match="records no revision"):
        head.parse(head.HEADER, Path("head.txt"))


def test_parse_rejects_two_revisions():
    with pytest.raises(AlembicLinearError, match="more than one revision"):
        head.parse("abc\ndef\n", Path("head.txt"))


def test_parse_points_at_rebase_when_markers_are_present():
    text = head.HEADER + "<<<<<<< HEAD\naaa\n=======\nbbb\n>>>>>>> feature\n"
    with pytest.raises(AlembicLinearError, match="alembic-linear rebase"):
        head.parse(text, Path("head.txt"))


def test_parse_conflict_reads_both_sides():
    text = head.HEADER + "<<<<<<< HEAD\naaa\n=======\nbbb\n>>>>>>> feature\n"
    assert head.parse_conflict(text, Path("head.txt")) == ("aaa", "bbb")


def test_parse_conflict_skips_the_diff3_ancestor_section():
    text = (
        head.HEADER + "<<<<<<< HEAD\naaa\n||||||| merged common ancestors\nppp\n"
        "=======\nbbb\n>>>>>>> feature\n"
    )
    assert head.parse_conflict(text, Path("head.txt")) == ("aaa", "bbb")


def test_parse_conflict_returns_none_when_resolved():
    assert head.parse_conflict(head.render("abc"), Path("head.txt")) is None


def test_write_reports_change_and_then_idempotence(tmp_path: Path):
    path = tmp_path / "head.txt"
    assert head.write(path, "abc") is True
    assert head.write(path, "abc") is False
    assert head.write(path, "def") is True
    assert head.read(path) == "def"


def test_read_names_the_fix_when_the_file_is_missing(tmp_path: Path):
    with pytest.raises(AlembicLinearError, match="alembic-linear update"):
        head.read(tmp_path / "head.txt")
