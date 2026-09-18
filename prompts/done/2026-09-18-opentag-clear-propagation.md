---
name: 2026-09-18-opentag-clear-propagation
status: completed          # pending | completed | failed
created: 2026-09-18
model: sonnet
completed: 2026-09-18
result: >
  Converted _sync_opentag_identity from stateless to baselined (per-side
  _opt_uuid/_opt_slug merged into the existing filament Snapshot row).
  Implemented the state-machine table exactly as specified, added clear
  propagation via spoolman.update_filament (blank extras) and
  FilamentDBClient.remove_filament_settings_keys (scoped exception, no new
  write path). Extended test_engine_opentag_identity.py from 7 to 15 tests
  (all passing); full backend suite 1499 passed; ruff clean. Updated
  docs/sync-model.md and added a 2026-09-18 docs/decisions.md entry (index
  regenerated). Fixes #89.
---

# Task: Make the OpenTag identity sync honor a deliberate unlink (GitHub #89)

Filament DB 1.77.0 (`hyiger/filament-db#1150`) added **Change link** / **Remove link** to the
OpenPrintTag dialog — the first FDB-side way to CLEAR an OpenTag link. The bridge's
`_sync_opentag_identity` pass (`core/engine.py:4288`) is deliberately **stateless (no
snapshot baseline)** and fills whichever side is empty, which is correct only while "empty"
can only mean *never linked*. It now also means *deliberately unlinked* — so the next cycle
writes the identity straight back and silently undoes the user's action, every time.

Read **GitHub issue #89** (`gh issue view 89`) first — it has the full analysis.

**The design call is already made (user decision, 2026-09-18): propagate the clear.** Do not
re-litigate it; implement it.

## Before you start

- `CLAUDE.md` — the `settings{}` **scoped exception** (only `merge_filament_settings` /
  `remove_filament_settings_keys`, only the two OpenTag identity keys) and the
  refresh-both-snapshots invariant. Both are hard rules here.
- `docs/decisions.md`: the **2026-07-27** entry (#81, the bidirectional identity sync you
  are modifying) and the **2026-09-18** entry (the compat review that found this).
- The **multicolor pass at `core/engine.py:975-1070` is your structural template** — a
  baselined, bidirectional, snapshot-diffed pass on the *same* `material_properties` axis
  with the same conflict semantics. Copy its shape, not its first-sight rule (see below).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files this
plan needs to modify. If any have uncommitted changes, list them and ask before touching
them. Surface unrelated dirty files once as awareness; don't block. This file is exempt.

## What to do

Convert `_sync_opentag_identity` from stateless to snapshot-baselined.

1. **Store a baseline per side.** Filament-level snapshots already exist and are used
   exactly this way — `_merge_snapshot(db, "spoolman", "filament", str(sm_id), {"_mc_sig": …})`
   in the multicolor pass. Store `_opt_uuid` (and `_opt_slug` alongside, so the pair stays
   consistent) on both the `"spoolman"` and `"filamentdb"` filament snapshots. **No alembic
   migration** — snapshot `data` is a JSON blob.

2. **Implement this state machine** (per mapping, after the existing synthetic-parent skip).
   `uuid` is the canonical key, as today. Treat a blank-string extra as empty — the bridge
   blanks Spoolman extras with `encode_extra_value("")` rather than deleting the key.

   | Baseline for that side | Current value | Action |
   |---|---|---|
   | absent (never seen) | side empty, other side set | **fill** — today's behavior, gated as today. Preserves #81. |
   | had a value | side now empty | **deliberate clear → propagate the removal to the other side**, direction-gated |
   | both set and equal | — | no-op; refresh baselines |
   | both set and differ | — | conflict, deduped, never overwrite — unchanged from today |
   | both now empty | — | converged; refresh baselines to empty, no writes |

   A clear on one side **plus** a change on the other is a genuine divergence → route it
   through `resolve_sync_action` and queue a conflict like the existing divergence case.

   **Do NOT adopt the multicolor pass's "first sight → store baseline, no write" rule.** A
   never-filled side would be baselined as empty and then never filled, which would regress
   #81. Absent baseline + empty side = fill, as the table says.

3. **Propagation needs no new write code.** `api/opentag.py:500 _clear_opentag_identity`
   already does both legs: blanks the two Spoolman extras with `encode_extra_value("")` and
   calls the scoped `remove_filament_settings_keys()` on FDB. Reuse those two primitives
   (extract a shared helper if that's cleaner than importing from the API layer — engine
   importing from `api/` would be the wrong direction). FDB writes MUST go through
   `remove_filament_settings_keys` and touch only the two identity keys.

4. **Refresh BOTH baselines after any propagation** to the post-write agreed value
   (including to empty after a clear) — the hard invariant, and what stops the clear being
   re-detected as a change next cycle.

5. **Keep the existing behavior intact otherwise**: direction gating via
   `resolve_sync_action` on the `material_properties` axis (`allow_fdb_to_sm` /
   `allow_sm_to_fdb`), deduped `cross_system` conflicts with
   `field_name="OpenPrintTag identity"`, dry-run emitting `result.preview` rows and
   performing no writes or queues, and the per-filament error handling.

Note: the bridge's **own** OpenTag Cleanup unmatch already clears both sides, so it is
unaffected either way. This is about a clear made natively in FDB or directly in Spoolman.

## Tests

Extend `backend/tests/test_engine_opentag_identity.py` (7 tests today — keep them passing):

- FDB-side unlink (baseline had a uuid, FDB now empty, SM still set) → **SM extras blanked,
  FDB not refilled**.
- SM-side unlink → FDB identity keys removed via `remove_filament_settings_keys`.
- Never-linked side still fills — the **#81 regression guard**.
- A second cycle after a clear performs **no writes** (anti-ping-pong).
- Divergent uuids still queue one deduped conflict and overwrite nothing.
- Direction gating blocks each leg independently.
- Dry-run emits preview rows and performs no writes/queues.

## Conventions to honor

- Match surrounding style; no new deps.
- **CHANGELOG.md `## [Unreleased]`** gets an entry in the SAME commit — a `### Fixed`
  bullet explaining the upstream cause and the new semantics, ending `Fixes #89.`
- Docs ship with the code: update `docs/sync-model.md` / `docs/opentag-matching.md` where
  they describe the identity pass as stateless fill-the-empty-side.
- `docs/decisions.md`: add a dated entry recording the state machine and **why** propagate
  was chosen over queue-a-conflict (the user already made a decision they had explicitly
  made in the FDB UI). Then re-run `scripts/gen-decisions-index.py` and add your heading to
  its `CATEGORIES` list.
- Conventional-commit prefix `fix:`. **No `Co-authored-by:` trailers.** Commit body ends
  with `Fixes #89`.
- Run before committing: `cd backend && .venv/bin/python -m pytest` and
  `.venv/bin/python -m ruff check backend/` (from the repo root for the ruff path).
- **Never push.**

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/`.
3. Propose ONE commit covering the files you modified (including the prompt move).
   Present the file list and the message; ask `commit these as "<message>"? (y/n)`.
   Stage those specific paths — never `git add -A`. Commit on the current branch.
