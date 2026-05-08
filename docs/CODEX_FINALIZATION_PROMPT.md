# Master Prompt — Codex GPT-5.5-high

**Copy everything below the `---` line into Codex. Don't include this header.**

---

# Mission

You are inheriting a 1:1 faithful port of an n8n workflow (`legacy/EL.json` + `legacy/el_error_handler.json`) into Python. **All 63 functional nodes are ported.** Your job is the final hardening pass: find latent bugs, close test gaps, stress-test the edges, and leave the codebase deployment-ready. No new features. No refactors that aren't fixing a real bug.

You are operating with **GPT-5.5 high reasoning**. Use it. Read carefully, audit aggressively, fix surgically.

---

# Repo Map

| Path | What it is |
|---|---|
| `legacy/EL.json`, `legacy/el_error_handler.json` | **Source of truth.** Every Python node must match its JS counterpart's behavior. Don't drift. |
| `el/nodes/*.py` | 63 ported nodes. Each has a `run(ctx, *, provider=None) -> ctx` signature. |
| `el/google_sheets.py`, `el/google_drive.py`, `el/supabase.py`, `el/telegram.py` | IO providers. Tests pass `Fake*Provider` instances. |
| `el/config.py`, `el/logger.py` | Env-var loading + structured logging. |
| `tests/test_*.py` | 368 passing tests. **Baseline must not regress.** |
| `docs/PORT_LOG.md` | Iteration journal — read top entries to understand recent decisions. |

**Test command (Windows PowerShell):**
```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

**Current baseline:** `368 passed in <1s`.

---

# Quality Bar (Non-negotiable)

These come from prior iterations and are load-bearing — violating any of them is a regression:

1. **Faithfulness over cleanup.** If the JS does something dumb, the Python does the same dumb thing. The n8n workflow is the spec. Don't editorialize.
2. **Fail-soft at boundaries.** IO nodes (Sheets, Drive, Supabase, Telegram, HTTP) NEVER raise. They write `{"ok": False, "error": str(exc)}` to ctx and return. Error-path nodes (`error_formatter`, `telegram_alert`) especially must never crash — they're the last line of visibility into upstream failures.
3. **Type-check at the door.** Every node treats `None`, wrong-type, and missing the same way: skip with a safe default. Never trust ctx values to be the type you expect. Patterns already established: `_safe_dict()`, `_to_float()`, `_safe_alpha_beta()`, `_parse_json_field()`, `_extract_first_json_array()`.
4. **No backwards-compat shims.** No `# removed` comments, no renamed `_unused` vars, no re-exports. If something is dead, delete it.
5. **No comments explaining WHAT.** Only the WHY of non-obvious decisions. Test docstrings should name the original failure mode (e.g. "Regression: greedy regex spanned two arrays").
6. **Provider injection.** Every IO node accepts `provider=None` so tests can pass fakes. Don't break this contract.
7. **Windows is a target.** No `zoneinfo("Asia/Kolkata")` (needs `tzdata` on Windows). Use `timezone(timedelta(hours=5, minutes=30))` for IST since IST has no DST. Watch for any other platform-specific traps.

---

# Deliverables (in order)

## 1. Audit Pass — Find Latent Bugs

Read **every** node in `el/nodes/` looking for the following patterns, which already bit us in Iter 11.1:

- [ ] `from zoneinfo import ZoneInfo` or any `ZoneInfo("...")` call → replace with fixed-offset `timezone(timedelta(...))`. Verify on every node.
- [ ] Non-greedy regex (`.*?`) where input might contain nested matches → replace with proper parser (see `parse_agent_output._extract_first_json_array` for the balanced-bracket pattern).
- [ ] Greedy regex (`.*`) where input might contain multiple matches → same problem, opposite direction.
- [ ] `ctx[key][0]` indexing without empty/list-type/dict-type guards.
- [ ] `.lower()`, `.strip()`, `.upper()`, `.split()` on values that might be `None`.
- [ ] Division where denominator could be zero (Beta calibration was the prior hit — check any other arithmetic).
- [ ] `dict.get("a").get("b")` chains where intermediate might be `None`.
- [ ] `json.loads(...)` without try/except.
- [ ] `requests.post/get` without `raise_for_status` or timeout.
- [ ] `int(...)`, `float(...)` on user-controlled values without try/except.
- [ ] Bare `except:` (must be `except Exception:` or specific).
- [ ] String slicing (`x[:300]`) on values that might not be strings.

For each bug found: fix it, add a regression test with a docstring naming the failure mode, and note it in your final report.

## 2. Coverage & Stress Tests

- [ ] Run `.venv\Scripts\python.exe -m pytest tests/ --cov=el --cov-report=term-missing` (install `pytest-cov` if needed). Identify any node under 90% line coverage. Add tests to close the gap. Skip pure framework glue (`__init__`, logger setup).
- [ ] Add **one** integration test that runs a representative chain end-to-end with all-fake providers — e.g. `youtube_trending → fetch_score_dedupe_rank → filter_top_30 → curate_picks → parse_agent_output`. Assert ctx flows correctly between nodes. File: `tests/test_integration_pipeline.py`. Don't try to wire all 63 — pick the longest faithful chain you can construct from the JS connections graph.
- [ ] Add stress cases to existing tests where missing:
  - Empty list inputs
  - `None` inputs at every public field
  - Non-dict / non-list polymorphic inputs
  - Unicode + emoji in strings (Telegram, error messages, sheet rows)
  - Very long strings (>10kb) where the node might truncate
  - Malformed JSON in any JSON-parse path

## 3. Penetration / Robustness

The "attacker" here is corrupt data, not a malicious user — but think adversarially:

- [ ] What happens if `ranked_payload` is a 100MB string? (Error-formatter slices `[:300]` already; verify others.)
- [ ] What if Tavily/Browserbase returns HTML instead of JSON? (`json.loads` must be guarded.)
- [ ] What if Supabase returns a single dict instead of a list? (`SupabaseRestProvider` already coerces — verify call sites trust this.)
- [ ] What if Telegram callback `data` is missing the colon-separator? (Parse must not raise.)
- [ ] What if `cj_top_products[].image_urls` is a list (already parsed) vs string (needs parsing)? Both must work.
- [ ] What if two pipeline runs collide on the same `run_date`? Verify upsert conflict columns are correct.

## 4. Debugging Sweep

- [ ] Run pytest 50× in a tight loop. Any flaky tests? Fix the root cause (don't `pytest-rerunfailures` over it).
- [ ] Run `python -W error -m pytest tests/ -q` — promote warnings to errors. Fix anything that surfaces.
- [ ] `python -m compileall el/ tests/` — must succeed silent.
- [ ] Grep for `TODO`, `FIXME`, `XXX`, `HACK` in `el/`. Each one: either fix it or delete the comment.
- [ ] Grep for `print(` in `el/` (logging only — no stray prints).

## 5. Finalization

- [ ] **`README.md`** — verify it reflects current state. Sections: setup (`.venv`, `pip install -r requirements.txt`), env vars (point to `.env.example`), running tests, running the workflow.
- [ ] **`.env.example`** — every `config.require()` and `config.get()` call site must have a documented entry. Audit by grepping.
- [ ] **CLI entry point** — if missing, add `python -m el run` that loads `.env`, constructs default providers, and runs the full pipeline. If present, verify it works.
- [ ] **`docs/PORT_LOG.md`** — add a final "Iter 13 — Hardening & finalization" entry at the top, summarizing every fix you made, every test you added, coverage delta, and the final test count. Put **"Port status: 63/63 (100%) — production-ready"** at the bottom.
- [ ] **`requirements.txt`** — pin all transitive versions or document why not. No floating `>=` on critical deps.

---

# What NOT to Do

- ❌ Don't add features that aren't in `legacy/EL.json`.
- ❌ Don't refactor for "cleanliness" — only refactor if fixing a bug requires it.
- ❌ Don't introduce new abstractions, base classes, or DI frameworks.
- ❌ Don't rename existing public functions/constants/ctx keys.
- ❌ Don't change provider signatures — tests rely on them.
- ❌ Don't bypass `--no-verify` or skip hooks.
- ❌ Don't `git push` or `git rebase`.
- ❌ Don't add new dependencies unless absolutely required (and document why).
- ❌ Don't write multi-paragraph docstrings. One short line max, only when WHY is non-obvious.

---

# Workflow

1. Read `docs/PORT_LOG.md` top 3 entries (Iter 12, Iter 11.1, Iter 11). Internalize the bulletproofing pattern.
2. Read every file in `el/nodes/`. Audit against Section 1 checklist.
3. Make fixes in small, focused commits. Each commit message follows the style in `git log` (e.g. `fix(port): iter 13.1 — <one line>`).
4. Run the full suite after every fix. Never commit a red suite.
5. Do Sections 2 → 3 → 4 → 5 in order.
6. Final commit: `feat(port): iter 13 — hardening + finalization (port 100% production-ready)` — should include the PORT_LOG entry and README updates.

---

# Final Report Format

When done, output exactly this report (and nothing else):

```
## Iter 13 Final Report

### Bugs found & fixed
- [file:line] <one-line description> — fixed by <approach>
- ...

### Tests added
- tests/<file>::<test_name> — covers <scenario>
- ...

### Coverage delta
Before: <%>  After: <%>

### Test count
Before: 368  After: <N>

### Files touched
- <path> — <reason>
- ...

### Outstanding concerns (if any)
- <thing you couldn't fix and why>

### Verification
- pytest: <N> passed
- compileall: ok
- python -W error pytest: ok
- 50× loop: 0 flakes

Port status: 63/63 (100%) — production-ready.
```

---

# Constraints Recap

- Source of truth = `legacy/EL.json`.
- Test baseline = 368 passing. Cannot regress.
- Pattern = type-check inputs, treat None/wrong-type as missing, fall back to safe defaults, error-path nodes never raise.
- Platform = Windows + Linux. No tz-database dependencies.
- Style = no comments unless WHY is non-obvious. No new abstractions. Faithful to JS even when the JS is dumb.

Begin with the audit. When in doubt, read the JS source in `legacy/EL.json` and match it.
