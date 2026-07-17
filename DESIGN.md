# alembic-linear-migrations — design

Repo: `~/projects/alexsavio/alembic-linear-migrations` → `alexsavio/alembic-linear-migrations`
PyPI: `alembic-linear-migrations` (verified free, 404)
License: MIT

## Problem

Two branches each add a migration with the same `down_revision`. Git merges both
cleanly — they are separate files that never touch. Alembic only objects later:

```
Multiple head revisions are present for given argument 'head'
```

By then the mistake is on the shared branch and someone has to untangle it, often
under deploy pressure. The failure is *late* and *far* from the cause.

## Solution

Record the head revision in one tracked line. Every new migration rewrites it.
Two branches → same line, different values → **git conflict at the moment the
branches meet**, which is the moment a human can still cheaply fix it.

Prior art: `django-linear-migrations` (`max_migration.txt`). No Alembic equivalent
exists; `sergio-voxy/alembic-linear-migrations` is a 4-day, 15-line shell script
with 0 users, hashing the file list into `versions_hash.txt`.

## Design decisions

### D1 — File location: `<script_location>/head.txt`

Next to `env.py` / `script.py.mako`, **not** inside `versions/`.

- One head file = one migration graph = one head. Conceptually exact.
- Zero risk of Alembic trying to interpret a stray non-`.py` file in `versions/`.
- Independent of how many `version_locations` are configured.

Rejected: `versions/head.txt` (Django puts it with the migrations, but Alembic's
`versions/` is a scanned module dir, and `version_locations` may be plural).

### D2 — Format: comment header + one bare revision line

```
# alembic-linear-migrations
# Records the current head of the migration graph.
# A conflict here means two branches added a migration from the same parent.
# Resolve with:  alembic-linear rebase
#
c4e6a8b0d2f1
```

The header is byte-identical on both sides, so it merges silently; only the last
line conflicts. The header is the point: whoever hits the conflict is told what it
means and how to fix it, in place, without reading docs.

Rejected: opaque hash (sergio-voxy). A hash conflict tells you nothing and can only
be resolved by regenerating. A revision id is greppable, and `rebase` can act on it.

Rejected: `<revision>  <filename>` — redundant, and churns on rename.

### D3 — Two triggers, deliberately overlapping

**(a) Alembic `post_write_hook`** — fires on `alembic revision` / `make-migrations`.
Empirically verified to fire through advanced_alchemy's CLI wrapper.

```ini
[post_write_hooks]
hooks = alembic_linear
alembic_linear.type = console_scripts
alembic_linear.entrypoint = alembic-linear-update
alembic_linear.options = REVISION_SCRIPT_FILENAME
```

**(b) pre-commit hook** — catches hand-written migrations that never went through
the CLI. This is sergio-voxy's genuine insight and the gap in a hook-only design.

```yaml
- id: alembic-linear          # rewrites head.txt, fails if it changed (black-style)
- id: alembic-linear-check    # read-only, for CI
```

`always_run: true`, `pass_filenames: false`. Loading 67 scripts is <100ms.

### D4 — CLI: `alembic-linear <update|check|rebase>`

- `update` — recompute `head.txt` from the graph.
- `check` — exit 1 if multiple heads, or `head.txt` stale. CI + pre-commit.
- `rebase` — resolve a conflict (below).

Config discovery: `-c/--config`, else search cwd upward for `alembic.ini`.
Uses `ScriptDirectory.from_config`, which does **not** execute `env.py` — so it is
static, needs no database, and cannot import app code. Important: it must stay
runnable in a pre-commit hook with no app environment.

### D5 — `rebase`: the reason this isn't 15 lines of shell

After a conflict, both migrations are present → the graph has exactly 2 heads.

```
alembic-linear rebase
```

1. Assert exactly 2 heads (else bail with a clear message).
2. Decide which is *ours*:
   - `.git/MERGE_HEAD` exists → merge: `HEAD` side is ours.
   - `.git/rebase-merge|rebase-apply` exists → **rebase: sides are inverted**, `HEAD` is upstream.
   - Neither → require explicit `--onto <rev>`.
3. Re-point our migration's `down_revision` → their head.
4. Write `head.txt` = our revision.
5. Re-assert a single head; refuse to leave the tree in a worse state.

The ours/theirs inversion under rebase-vs-merge is the subtle bit most
hand-rolled versions get wrong, and it is exactly what a library should own.

### D6 — Scope limits (documented, not silently broken)

- Only for **linear** histories. Projects deliberately using Alembic branch labels
  with legitimate multiple heads are out of scope — `check` says so plainly rather
  than crashing.
- Solves **ordering**, not semantics. Two branches adding the same column is a
  schema conflict no tool can auto-resolve (Danjou's caveat applies equally here).

## Package

- `pyproject.toml`, hatchling, MIT, Python >=3.10, dep `alembic>=1.9`.
- Entry points: `alembic-linear`, plus `alembic-linear-update` for the hook.
- `.pre-commit-hooks.yaml` for pre-commit consumers.
- pytest, ruff, mypy. CI matrix over Python + Alembic versions.
- PyPI publish on tag via trusted publishing (no token in secrets).

## Build order

- [ ] Repo skeleton: pyproject, MIT LICENSE, ruff/mypy config, src layout
- [ ] `config.py` — locate + load alembic.ini, resolve script_location
- [ ] `head.py` — read/write/parse head.txt (header-aware)
- [ ] `update` + `check` commands
- [ ] `post_write_hook` entry point; verify `console_scripts` type end-to-end
- [ ] `.pre-commit-hooks.yaml` + verify in a scratch repo
- [ ] `rebase` — merge/rebase side detection, down_revision rewrite
- [ ] Tests: fixture alembic projects (linear, 2-head, stale head, hand-written)
- [ ] README: problem, install, wiring, rebase workflow, limitations
- [ ] CI + PyPI trusted publishing
- [ ] v0.1.0

## Then: adopt in analysis-virtual-machines

Separate PR, after v0.1.0 is real. Wires `[post_write_hooks]` + pre-commit +
`head.txt` = `c4e6a8b0d2f1`, and #2706 gets the first real conflict guard.
