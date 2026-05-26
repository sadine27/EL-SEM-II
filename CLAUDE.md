# CLAUDE.md — instructions for Claude Code sessions

This file is auto-loaded by Claude Code at session start. It tells Claude
how to navigate this repository and what discipline to keep.

## 1. Read this first

**Always open `AI_CONTEXT.md` before doing anything else.** It is the
single source of truth for:

- what the project is and is for,
- which sub-projects (SPs) are done vs in-flight vs not started,
- where each kind of file lives,
- the project-wide conventions (fail-soft, ctx dict, fakes-only tests, etc.),
- the prioritized list of outstanding work.

Do not re-derive any of that from the README, the roadmap, or commit
history when `AI_CONTEXT.md` already states it.

## 2. Keep `AI_CONTEXT.md` current

`AI_CONTEXT.md` is only useful if it matches reality. The rule:

> **Any commit that changes status, scope, dependencies, env vars, or
> top-level layout must update `AI_CONTEXT.md` in the same commit.**

Specifically, update it when you:

- merge or partially advance a sub-project (update §3 status table),
- finish or start a piece of outstanding work (update §6),
- add a new top-level directory or significant module (update §4),
- introduce a new env var or remove one (mention in §4 or §5),
- change a project-wide convention (update §5).

Always bump the `Last updated:` date at the top.

If the change is purely internal (a single-file refactor, a typo fix, a
test rename), `AI_CONTEXT.md` does not need to move.

## 3. Other discipline expected here

- **TDD where it pays off.** New `el/` modules and nodes start with a
  failing test in `tests/`. Infrastructure files (Dockerfile, compose,
  CI yaml) use "write + smoke test + commit" instead.
- **Fail-soft at IO boundaries.** Match `tests/test_hardening_edges.py`.
- **Fakes in tests, never live network.** Use the fixtures in
  `tests/conftest.py` and `tests/web/conftest.py`.
- **Conventional Commits with SP prefix.** `feat(sp8): …`,
  `test(sp1): …`, `docs(phase3): …`, `chore(sp8): …`.
- **One SP at a time.** Never two `feat/spN-*` branches in flight.
- **Source of truth for ported nodes is `legacy/EL.json`.** When node
  behavior is ambiguous, read the JS in that file and match it.
- **No re-introducing deleted bloat.** The `docs/` and `legacy/`
  directories were cleaned on 2026-05-26 to remove orphan binaries,
  pre-port helpers, and one-time prompts. If you find yourself adding
  `*.docx`, `*.jam`, FigJam exports, or "Codex prompt" files, stop
  and ask whether they belong in the repo at all.

## 4. Pointers (also in `AI_CONTEXT.md`)

- Roadmap: `PHASE3_ROADMAP.md`
- Per-SP design specs: `docs/superpowers/specs/`
- Per-SP plans: `docs/superpowers/plans/`
- Per-SP iteration logs: `docs/SP*_LOG.md`
- Port iteration log: `docs/PORT_LOG.md`
- Env vars: `.env.example` (numbered sections, one per provider)
- Runbooks: `docs/runbooks/`
