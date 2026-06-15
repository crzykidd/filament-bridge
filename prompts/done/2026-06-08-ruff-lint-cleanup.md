---
name: 2026-06-08-ruff-lint-cleanup
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: ruff 74→0 errors; 55 auto-fixed (F401); 19 manual fixes (F841/F811/E402/E731) — all dead code, no real bugs found; 708 pytest pass
---

# Task: Fix ruff lint errors in backend/ (CI runs `ruff check backend/`)

CI runs `ruff check backend/` with default rules (no ruff config). It currently reports ~74
errors, mostly leftovers from rapid iteration: ~56 F401 (unused imports), ~13 F841 (unused
local variables), ~4 E402 (module import not at top of file), ~2 F811 (redefinition),
1 E731 (lambda assignment), and a couple others. Get `ruff check backend/` to ZERO errors
WITHOUT breaking anything.

ruff is installed at `~/.local/bin/ruff` (v0.15.16) — use `ruff` (or `~/.local/bin/ruff`).

## Approach — fix with judgment, do NOT blind-delete

1. **Auto-fix the safe ones**: run `ruff check backend/ --fix`. This clears the F401 unused
   imports and other safe fixes. Review the diff — make sure no removed import was actually a
   re-export (e.g. in `__init__.py`) or imported for a side effect; ruff handles `__all__`
   re-exports, but eyeball anything suspicious.
2. **F841 (unused local variable)** — for EACH, decide: is it genuinely dead (remove it), or
   does it reveal a BUG (a computed value that was supposed to be used)? Today's work touched
   engine.py, wizard.py, opentag.py, etc. — an assigned-but-unused result could be a real
   logic gap. If it looks like a bug, fix the bug (use the value) rather than deleting; if truly
   dead, remove. Note any you judged as bugs in your report.
3. **F811 (redefinition of unused name)** — two defs/imports sharing a name. This is often a
   real problem (a duplicate function/import shadowing another). Investigate each and fix
   correctly (remove the dead duplicate, or rename if both are needed). Do NOT just suppress.
4. **E402 (import not at top)** — if it's an intentional lazy/local import to avoid a circular
   import (e.g. `from app.config import settings as _settings` deliberately inside a function
   is fine and won't trip E402; E402 is about MODULE-LEVEL imports placed after code), move the
   import to the top if safe; if it's intentionally placed (e.g. after a `sys.path` tweak or to
   break a cycle) add a targeted `# noqa: E402` with a brief reason.
5. **E731 (lambda assignment)** — convert `x = lambda ...` to a `def`.
6. Anything else — fix appropriately.

Do NOT add a broad ruff-ignore config to mask errors. A minimal `[tool.ruff]` config in
`backend/pyproject.toml` is acceptable ONLY if you need to set `target-version`/`line-length`
to match the code — but do not disable rule categories to hide these errors.

## Verification

- `ruff check backend/` → "All checks passed!" (0 errors).
- `cd backend && pytest` → still all green (the lint fixes must not change behavior; if you
  fixed a real F841/F811 bug, ensure tests still pass and note it).

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. If you fixed any genuine bug (not just dead code), add a one-line note to `docs/decisions.md`.
3. Non-interactive subagent run: when ruff is clean AND pytest passes, stage ONLY the files
   this task touched (incl. prompt move) and commit on `dev` with one `chore:` message (or
   `fix:` if you fixed a real bug). Never `git add -A`. Never push.
