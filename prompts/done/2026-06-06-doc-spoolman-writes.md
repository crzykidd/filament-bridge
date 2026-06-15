---
name: 2026-06-06-doc-spoolman-writes
status: completed        # pending | completed | failed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: created docs/spoolman-writes.md; all facts verified against engine.py, wizard.py, and spoolman.py — authored content was accurate
---

# Task: Document every field the bridge writes to Spoolman (docs/spoolman-writes.md)

Create a new reference doc `docs/spoolman-writes.md` capturing every field the bridge
writes to Spoolman and when. The full content is authored below. Your job: **verify each
claim against the current code, correct anything that has drifted, then create the file
and commit it.** This is docs-only.

## Before you start

- Read `CLAUDE.md`. Commit prefix for docs-only changes is `docs:`. Work on `dev`, no
  `Co-authored-by:` trailer.
- VERIFY the authored content below against current code before writing it — do not trust
  the line numbers blindly (the engine/wizard shifted across recent commits). Key sources
  to check: `backend/app/services/spoolman.py` (`_REQUIRED_SPOOL_FIELDS`,
  `ensure_extra_fields`, the write methods), `backend/app/core/engine.py` (weight,
  multicolor, cost, field-mapping, new-spool passes), `backend/app/api/wizard.py`
  (`_execute_spoolman_to_fdb`, `_execute_fdb_to_spoolman`, `_compute_sm_reconcile_patch`,
  `_sm_filament_payload_from_fdb`, vendor creation), `backend/app/config.py`
  (`SPOOLMAN_FIELD_*`). Fix the doc if any field/trigger is wrong. Drop the inline
  file:line refs from the final doc (they go stale) — keep references to function/pass
  names instead.

## Working tree check

`git status --porcelain` — files: `docs/spoolman-writes.md` (new), and add a one-line
pointer to it from `CLAUDE.md` (in the docs list / project structure) and/or `docs/prd.md`
if there's a natural index. Ignore unrelated untracked home-dir dotfiles. This prompt is
exempt.

## Authored content (verify, then write to docs/spoolman-writes.md)

```markdown
# Spoolman writes reference

Every field filament-bridge writes to Spoolman, and when. The bridge interacts with
Spoolman in two contexts: **structural setup** (custom fields it registers) and **data
writes** (the one-time wizard import, and ongoing auto-sync cycles). The bridge only ever
uses documented Spoolman REST APIs; it never deletes Spoolman records.

## Custom extra fields the bridge registers

Created once at startup (`ensure_extra_fields()`), on the **spool** entity. Key names are
overridable via env vars (`SPOOLMAN_FIELD_FILAMENTDB_ID`,
`SPOOLMAN_FIELD_FILAMENTDB_PARENT_ID`, `SPOOLMAN_FIELD_FILAMENTDB_SPOOL_ID`):

| Field key | Type | Purpose |
|---|---|---|
| `filamentdb_id` | text | FDB filament ID (cross-reference link) |
| `filamentdb_parent_id` | text | FDB variant parent ID |
| `filamentdb_spool_id` | text | FDB spool subdocument ID |

These three extras are the only additions to Spoolman's schema. They are stored
JSON-encoded (`encode_extra_value`). Everything below writes native Spoolman fields or
these extras.

## Ongoing auto-sync writes (per cycle, change-driven)

These are **Filament DB → Spoolman** writes. Each fires only when the category's
configured **sync direction + conflict policy** routes the change to Spoolman (two-way
lone change, one-way FDB→SM, or an FDB-winning conflict policy). See
[the sync direction/conflict model](decisions.md).

| Entity | Field(s) | Trigger |
|---|---|---|
| Spool | `remaining_weight` (net; converted from FDB gross via `fdb_to_spoolman_net`) | Weight sync resolves FDB→SM for the pair |
| Filament | `color_hex`, `multi_color_hexes`, `multi_color_direction` | Multicolor sync resolves FDB→SM (Filament DB ≥ 1.33.0) |
| Filament | `price` | Cost sync resolves FDB→SM (filament price only — never per-spool price) |
| Spool | `extra.{mapped field}` | Generic field-mapping sync (FR-11) resolves FDB→SM; arbitrary mapped FDB fields stored as spool extras |

New-spool creation during a cycle (gated by `new_spool_sync_direction`):

| Entity | Op | Field(s) | Trigger |
|---|---|---|---|
| Spool | create | `filament_id`, `remaining_weight`, + the 3 cross-ref extras | A new FDB spool has no Spoolman counterpart |
| Spool | update | the 3 cross-ref extras | After creating an FDB spool from a new SM spool — links it back |

## Wizard initial-import writes (one-time, on Execute)

**Filament DB → Spoolman import direction:**

| Entity | Op | Field(s) |
|---|---|---|
| Vendor | create | `name` (deduplicated by normalized name) |
| Filament | create | `name`, `material`, `color_hex`, `density`, `spool_weight`, `vendor_id` |
| Spool | create | `filament_id`, `remaining_weight`, + 3 cross-ref extras |

**Spoolman → Filament DB import direction:**

| Entity | Op | Field(s) | Trigger |
|---|---|---|---|
| Spool | update | 3 cross-ref extras | After creating the FDB spool — links it back |
| Filament | update | `material`, `density`, `diameter`, `settings_extruder_temp`, `settings_bed_temp`, `spool_weight` | Variances **reconcile write-back** — only fields the user corrected, and only where the value differs from current Spoolman |

## What the bridge never writes to Spoolman

`location`, `lot_nr`, `archived`, `comment`, and **per-spool `price`** (cost write-back
targets the filament price only). The bridge never deletes Spoolman records.

## Notes

- **Weight is always net-converted** on the way in (`fdb_to_spoolman_net`), since FDB
  stores gross (filament + reel tare) and Spoolman stores net (filament only).
- The Variances reconcile write-back is the only place the bridge *corrects existing*
  Spoolman filament data; all ongoing-sync writes are change-driven.
- Cross-reference extras are always JSON-encoded via `encode_extra_value` / decoded via
  `decode_extra_value` — never written raw.
```

## Conventions to honor

- `docs:` commit prefix, `dev` branch, no `Co-authored-by:`. Docs ship in this commit.
- If any authored fact is wrong after verification, fix the doc — accuracy first.

## Verification

- Cross-check every row against the current code (functions/passes named above). No code
  or tests change, so no pytest needed; but if you discover a behavior the doc misstates,
  correct the doc.

## When done

1. Frontmatter; `git mv` this prompt to `prompts/done/`.
2. (No `docs/decisions.md` entry needed — this is a reference doc, not a decision.)
3. Non-interactive subagent run: stage ONLY `docs/spoolman-writes.md`, the `CLAUDE.md`
   pointer edit, this prompt move, and commit on `dev` with one `docs:` message. Never
   `git add -A`. Never push.
