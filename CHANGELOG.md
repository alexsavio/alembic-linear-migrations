# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are
[CalVer](https://calver.org/) `YYYY.MM.MICRO`: the year and month of the release,
then a counter that starts at 0 each month. The git tag is the version, so cutting a
release means tagging `vYYYY.MM.MICRO`.

## [Unreleased]

### Fixed

- `rebase` now prints a clean error pointing at `--onto` when the graph has two
  heads but `head.txt` is absent, instead of raising a `FileNotFoundError`
  traceback.

## [2026.7.0] - 2026-07-19

First release.

### Added

- `head.txt` in `<script_location>`, recording the migration graph's head behind a
  comment header that explains a conflict in place.
- `alembic-linear update`, recompute `head.txt` from the graph.
- `alembic-linear check`, exit 1 if the graph has multiple heads or `head.txt` is
  stale. Read-only, for CI.
- `alembic-linear rebase`, resolve a two-branch conflict by re-pointing one branch's
  `down_revision` onto the other's head, accounting for git labelling the sides of a
  conflict differently under merge, rebase, and cherry-pick. `--onto` names the target
  explicitly when no git operation is in progress.
- Alembic `post_write_hook` entry point (`alembic-linear-update`, `console_scripts`
  type), verified against alembic 1.9 and 1.18.
- pre-commit hooks `alembic-linear` and `alembic-linear-check`.

[Unreleased]: https://github.com/alexsavio/alembic-linear-migrations/compare/v2026.7.0...HEAD
[2026.7.0]: https://github.com/alexsavio/alembic-linear-migrations/releases/tag/v2026.7.0
