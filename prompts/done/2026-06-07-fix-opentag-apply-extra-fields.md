---
name: 2026-06-07-fix-opentag-apply-extra-fields
status: completed        # pending | completed | failed
created: 2026-06-07
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: apply self-heals via ensure_extra_fields; per-section isolation + RequestError catch added; 7 new tests; 569 pass
---

# Task: Fix OpenTag apply errors — self-create the openprinttag extra fields; resilient ensure_extra_fields

The OpenTag Cleanup "apply" fails with errors for every filament. Root cause (verified
against the live Spoolman DB): the filament extra fields `openprinttag_slug` and
`openprinttag_uuid` were never created in Spoolman (only `filamentdb_material_tags` was), so
the apply's PATCH writes undefined extra keys → Spoolman 422 → per-filament error. The
fields are created in `ensure_extra_fields`, but that runs only at startup and is wrapped in
a swallow-all `try/except` (main.py:146), so a transient/partial failure leaves them missing
silently.

## What to do

### 1. Self-heal in the apply endpoint
In `backend/app/api/opentag.py` `opentag_apply`, BEFORE the decision loop, call
`await sm.ensure_extra_fields()` once (it's idempotent — only creates missing fields). Wrap
it so a failure returns a clear `api_error` (e.g. 502 `opentag_field_setup_failed`,
"Could not ensure the OpenTag extra fields exist in Spoolman: …") instead of letting the
first PATCH 422. This guarantees `openprinttag_slug`/`openprinttag_uuid`/
`filamentdb_material_tags` exist before any write.

### 2. Make ensure_extra_fields resilient (`backend/app/services/spoolman.py`)
- Wrap the **spool** section and the **filament** section independently so a failure in one
  (including the `get_field_definitions(...)` call, which is currently NOT in a try) does not
  abort the other. A failure to read/validate one entity's existing defs must not skip
  creating the other entity's fields.
- Broaden the per-field creation `except httpx.HTTPStatusError` to also catch
  `httpx.RequestError` (connection/timeout) so a transient blip on one field doesn't bubble
  up and abort the rest.
- Log creation failures clearly (key + status + body) so they're visible (the user saw
  nothing). Keep individual field creation idempotent (skip if key already exists).

### 3. Tidy
- Update the stale docstring in `main.py` / `ensure_extra_fields` (it still says "the three
  cross-ref fields"; it now also creates the filament fields material_tags + openprinttag
  slug/uuid).

## Verification

- `cd backend && pytest` — tests:
  - `opentag_apply` calls `ensure_extra_fields` before writing (mock the SM client; assert
    called, and that an apply succeeds when the fields were initially missing).
  - `ensure_extra_fields` still creates the filament fields even when the spool-section
    `get_field_definitions("spool")` or a spool-field POST raises (per-section isolation);
    and creates the remaining filament fields when one filament POST raises a
    `RequestError`.
  - idempotent: fields already present are not re-created.
- (No frontend change required; the apply will now succeed.)

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag apply self-creates required extra fields; ensure_extra_fields
   is per-section/resilient so a missing field can't silently break apply.
3. Non-interactive subagent run: when pytest passes, stage ONLY the files this task touched
   (incl. prompt move + docs) and commit on `dev` with one `fix:` message. Never
   `git add -A`. Never push.
