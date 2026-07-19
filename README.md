# alembic-linear-migrations

Turn a late Alembic `Multiple head revisions are present` error into an early git conflict.

[![PyPI](https://img.shields.io/pypi/v/alembic-linear-migrations.svg)](https://pypi.org/project/alembic-linear-migrations/)
[![Python versions](https://img.shields.io/pypi/pyversions/alembic-linear-migrations.svg)](https://pypi.org/project/alembic-linear-migrations/)
[![License](https://img.shields.io/pypi/l/alembic-linear-migrations.svg)](https://github.com/alexsavio/alembic-linear-migrations/blob/main/LICENSE)

## The problem

Two branches each add a migration from the same `down_revision`. They are separate
files that never touch, so git merges both without complaint. Alembic only objects
later, on someone else's machine or in a deploy:

```
Multiple head revisions are present for given argument 'head'
```

By then the mistake is already on the shared branch, and someone has to untangle it
under time pressure. The failure is late, and far from its cause.

## The fix

Record the migration graph's head in one tracked line. Every new migration rewrites
it. Two branches then write different values to the same line, so git raises a
conflict the moment the branches meet, which is the moment a human can still fix it
cheaply:

```
# alembic-linear-migrations
# Records the current head of the migration graph.
# A conflict here means two branches added a migration from the same parent.
# Resolve with:  alembic-linear rebase
#
<<<<<<< HEAD
8f2a1c9d4e7b
=======
c4e6a8b0d2f1
>>>>>>> main
```

The header is identical on both sides, so it merges silently and only the revision
line conflicts. Whoever hits it is told what it means and how to fix it, in place.

## Install

Install it into **the same environment as alembic**, as a dev dependency:

```bash
uv add --dev alembic-linear-migrations
# or: pip install alembic-linear-migrations
```

> **Not `pipx install` / `uv tool install`.** Alembic resolves the post_write_hook's
> entry point through its own environment's metadata. Installed in isolation it is
> invisible to alembic, which fails with
> `Could not find entrypoint console_scripts.alembic-linear-update`.

Then create the file:

```bash
alembic-linear update
git add migrations/head.txt
```

## Wiring

The two triggers overlap on purpose. The alembic hook covers migrations made through
the CLI; the pre-commit hook covers the ones that were not.

### 1. Alembic post_write_hook

Fires on `alembic revision` and `alembic revision --autogenerate`. In `alembic.ini`:

```ini
[post_write_hooks]
hooks = alembic_linear
alembic_linear.type = console_scripts
alembic_linear.entrypoint = alembic-linear-update
```

Already running hooks? Append to the list: `hooks = black, alembic_linear`.

### 2. pre-commit

Catches migrations written by hand, which never go through the CLI, so no hook fires.
In `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/alexsavio/alembic-linear-migrations
    rev: v2026.7.0 # or the latest tag
    hooks:
      - id: alembic-linear
```

| Hook id | Behaviour |
|---|---|
| `alembic-linear` | Rewrites `head.txt`, fails if it had to. For developers. |
| `alembic-linear-check` | Read-only, fails if stale. For CI. |

> **If your migrations import application code**, run the hook in your project's own
> environment instead. Alembic imports every migration file to read its revision ids,
> and pre-commit's isolated environment has alembic but not your app:
>
> ```yaml
>   - repo: local
>     hooks:
>       - id: alembic-linear
>         name: alembic-linear
>         entry: alembic-linear update --exit-on-change
>         language: system
>         always_run: true
>         pass_filenames: false
> ```

## Resolving a conflict

When git reports a conflict in `head.txt`, both migrations are already present, so the
graph has two heads. Leave the conflict markers alone and run:

```bash
alembic-linear rebase
```

It re-points your migration to sit on top of theirs, rewrites `head.txt`, and refuses
to finish unless the graph is left with exactly one head:

```
Re-pointed 8f2a1c9d4e7b onto c4e6a8b0d2f1.

  migrations/versions/8f2a1c9d4e7b_add_orders.py
    down_revision: a1b2c3d4e5f6 -> c4e6a8b0d2f1

  head.txt now records 8f2a1c9d4e7b, and the graph has one head.
```

Then review both migrations, `git add` them, and finish the merge or rebase.

Working out which side is yours is the part worth owning. Git labels the two sides of
a conflict `HEAD` and incoming, but which one holds *your* work inverts between
operations: `git merge` leaves your commit on the `HEAD` side, while `git rebase`
checks out the upstream first and replays your commit as the incoming side.
`rebase` reads the git state and accounts for that, so the outcome is the same either
way. When no merge or rebase is in progress there is nothing to infer from, so name
the other branch's head yourself:

```bash
alembic-linear rebase --onto c4e6a8b0d2f1
```

If your branch added several migrations, only the bottom one moves; the rest ride
along on top of it.

## Commands

| Command | Purpose |
|---|---|
| `alembic-linear update` | Recompute `head.txt` from the graph. |
| `alembic-linear check` | Exit 1 if the graph has multiple heads, or `head.txt` is stale. |
| `alembic-linear rebase` | Resolve a conflict between two branches. |

`-c/--config` points at an `alembic.ini`; otherwise the working directory and its
parents are searched. Reading the graph never executes `env.py`, so no command needs a
database or a running application.

## Limitations

- **Linear histories only.** Projects that deliberately use Alembic branch labels and
  expect several heads are out of scope. `check` says so plainly rather than crashing.
- **Ordering, not semantics.** This decides which migration runs first. Two branches
  that both add the same column are a schema conflict no tool can resolve for you;
  `rebase` orders them and tells you to read them.
- **`head.txt` has to be committed.** It is the conflict carrier. Untracked, it cannot
  conflict, and none of this works.

## Where the file lives

`<script_location>/head.txt`, next to `env.py`, not inside `versions/`. One migration
graph has one head, so one file describes it exactly, however many `version_locations`
are configured. Keeping it out of `versions/` also keeps a non-`.py` file out of a
directory alembic scans.

## Prior art

[`django-linear-migrations`](https://github.com/adamchainz/django-linear-migrations),
which does this for Django with a `max_migration.txt` per app. This is the same idea
fitted to Alembic, where one migration graph means one head file, and where resolving
a conflict means rewriting a `down_revision` while accounting for git's merge/rebase
inversion.

## License

MIT
