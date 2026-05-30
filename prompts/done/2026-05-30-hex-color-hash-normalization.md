---
name: 2026-05-30-hex-color-hash-normalization
status: completed
created: 2026-05-30
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-30
result: Added to_fdb_color/to_sm_color helpers; fixed SM→FDB write in wizard + engine; fixed FDB→SM write in wizard + engine; normalized color comparison in differ to stop flapping; 149 tests green
---

# Task: Normalize hex-color `#` prefix between Spoolman and Filament DB

Spoolman stores hex colors **bare** (`color_hex = "93BE2F"`); Filament DB stores/expects
them **`#`-prefixed** (`color = "#93BE2F"`). The bridge normalizes only the FDB→Spoolman
read (`wizard.py:386` does `.lstrip("#")`) and the matcher comparison
(`matcher.normalize_color`), but the **Spoolman→FDB write path never adds the `#`**, so
colors land in Filament DB as `93BE2F` instead of `#93BE2F`. Fix the write path in both
the wizard and the ongoing engine sync, in both directions, and stop the value from
flapping in the differ.

## Sequencing — read this first

**This depends on `2026-05-30-multicolor-colorname-mapping.md`.** That prompt creates
`backend/app/core/color.py` and edits the *same* color write sites (wizard create +
engine apply). Do NOT start this until that prompt has merged. Run `git log --oneline -5`
and confirm `core/color.py` exists; if it doesn't, STOP and tell the user the multicolor
work hasn't landed yet.

## Before you start

- **Read `CLAUDE.md`** — FDB/Spoolman data-model gotchas, the hard rules (never touch the
  `settings{}` bag, never raw-overwrite weight, conflicts never auto-resolve).
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.
- The convention is already established — match it:
  - `backend/app/core/matcher.py::normalize_color` strips `#` and lowercases for comparison.
  - `backend/tests/test_matcher.py:33` (`test_color_strips_hash`) documents `#FF0000` ≡ `ff0000`.

## Working tree check

Run `git status --porcelain`. Files this touches: `backend/app/core/color.py` (add helpers),
`backend/app/api/wizard.py` (create payload + display ref), `backend/app/core/engine.py`
(SM→FDB and FDB→SM color field sync), and `backend/tests/*`. If any are dirty, list and ask.
This prompt file is exempt.

## The bug (already located — don't re-discover)

- `backend/app/api/wizard.py:367` — `"color": sm.color_hex,` writes bare hex to FDB. **Primary bug.**
- `backend/app/api/wizard.py:70` — `_sm_ref(...).color = sm.color_hex` (display ref) is also bare.
- `backend/app/api/wizard.py:386` — `_sm_filament_payload_from_fdb` already does
  `(fdb.color or "").lstrip("#")` — correct; replace the inline call with the shared helper.
- `backend/app/core/engine.py:296-318` — the SM→FDB field-sync (`fdb_put_payload`) and the
  FDB→SM field-sync above it pass `color` through raw. If `color` is field-mapped this writes
  the wrong form AND the differ sees a perpetual bare-vs-`#` diff (flapping).

## What to do

### 1. Color-format helpers — `backend/app/core/color.py` (pure, no I/O)
- `to_fdb_color(value: str | None) -> str | None` — ensure exactly one leading `#`
  (`"93BE2F"` → `"#93BE2F"`, `"#93BE2F"` → `"#93BE2F"`); pass `None`/empty through as `None`.
  Do not change case (FDB round-trips whatever case it's given; only the `#` is the contract).
- `to_sm_color(value: str | None) -> str | None` — strip leading `#` (`"#93BE2F"` → `"93BE2F"`);
  `None`/empty → `None`.
- Keep these tiny and pure; reuse them everywhere a color crosses the boundary.

### 2. Fix the Spoolman→FDB write path
- `wizard.py` `_fdb_filament_payload_from_sm` (line ~367): `"color": to_fdb_color(sm.color_hex)`.
- `wizard.py` `_sm_ref` (line ~70): wrap with `to_fdb_color(...)` if the ref is used to build
  an FDB write, or leave bare if it's display-only — verify which and comment the choice.
- `engine.py` SM→FDB field-sync: when `fc.field_name == "color"`, normalize `new_value` with
  `to_fdb_color(...)` before adding to `fdb_put_payload`.

### 3. Fix the FDB→Spoolman write path
- `wizard.py` `_sm_filament_payload_from_fdb` (line ~386): replace the inline `.lstrip("#")`
  with `to_sm_color(fdb.color)`.
- `engine.py` FDB→SM field-sync: when the field is `color`, normalize the FDB value with
  `to_sm_color(...)` before writing the Spoolman extra field.

### 4. Stop the flap in the differ
- Wherever the differ compares the `color` field across snapshots, compare **normalized**
  values (reuse `matcher.normalize_color`, which already strips `#` + lowercases) so a
  bare-vs-`#` representation difference is NOT treated as a change. Confirm the snapshot
  stores a consistent form, or normalize at compare time. A round-trip (SM→FDB→SM) must
  converge — no endless updates.

## Conventions to honor

- `core/color.py` stays pure (no I/O). Delegate HTTP to existing clients.
- Never touch the `settings{}` bag; never raw-overwrite weight; structured logs, respect `LOG_LEVEL`.
- Match the existing helper/test patterns in `core/` and `tests/`.

## Verification

- `cd backend && pytest` green — new tests: `to_fdb_color`/`to_sm_color` for bare, `#`-prefixed,
  `None`, and empty inputs; SM→FDB create payload yields `#`-prefixed color; FDB→SM payload
  yields bare; a simulated SM→FDB→SM round-trip converges (differ reports no color change on the
  second cycle).
- **End-to-end on the local stack** (`docker-compose.dev.yml`, re-seed `private_data/spoolman-livedata.db`):
  run the wizard execute / a sync, then confirm in Filament DB that a created filament's `color`
  is `#`-prefixed (e.g. `#93BE2F`, not `93BE2F`). Trigger a second sync and confirm color does
  not flap (no spurious update in the sync log).

## When done

1. Update frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Add a short implementation note to `docs/decisions.md` only if something non-obvious changed
   (e.g. where the snapshot normalization landed).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `fix: prefix hex colors with # when writing to Filament DB`.
   Present the file list and ask `commit these as "<message>"? (y/n)` before staging. Stage
   specific paths only; commit on `dev`; no push.
