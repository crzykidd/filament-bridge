---
name: 2026-06-08-opentag-vendor-reassign-field
status: completed
created: 2026-06-08
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-07
result: "Vendor field added to OPT cleanup: shows only when SM vendor != OPT brand (normalized); apply resolves vendor_id via find-or-create (no duplicates); vendor reported in fields_written; 647 tests pass, frontend builds clean"
---

# Task: OpenTag cleanup — reviewable Manufacturer field (reassign Spoolman vendor to OpenTag brand)

When a match was found across a vendor-name difference (e.g. via the `prusa=prusament` alias,
or any case where the Spoolman vendor name differs from the OpenTag brand name), show
**Manufacturer** as a reviewable field in the cleanup, defaulting to the OpenTag brand value,
so the user can standardize the Spoolman vendor to match OpenTag — or keep-mine/ignore.

## What to do

### Backend — surface the field
- `opt_to_spoolman_fields` (`backend/app/core/opentag_match.py`): add
  `result["vendor"] = opt.get("brandName")` (the OpenTag brand name). (It's not a plain
  Spoolman scalar field — see the apply note — but it flows through the review like one.)
- `_build_field_rows` (`backend/app/api/opentag.py`): for the `vendor` field, the
  `spoolman_value` is the filament's current vendor name (`sm_fil.vendor.name if sm_fil.vendor
  else None` — make `_current_spoolman_value` handle `"vendor"`). **Only include the vendor
  row when it DIFFERS** from the OpenTag brand (normalized via `normalize_vendor`) — i.e. when
  an alias/name mismatch was involved. When the Spoolman vendor already equals the OpenTag
  brand, omit the row (nothing to change).
- The candidate/`fields` then carries the manufacturer row; the frontend renders it through
  the generic field-row UI (label "vendor"/"manufacturer", default OpenTag value, keep-mine).
  No special frontend needed beyond a friendly label if trivial.

### Backend — apply (vendor reassignment, find-or-create)
A vendor is a relation (`vendor_id`), not a scalar, so it can't go in the generic native
patch:
- `_build_sm_patch`: do NOT put `vendor` into the native patch. Instead extract the chosen
  vendor NAME (from the `vendor` field decision when not keep_mine and non-null) and return it
  separately (e.g. add a third element / a `vendor_name` to the returned structure).
- In `opentag_apply`: when a `vendor_name` is chosen, resolve it to a Spoolman `vendor_id`
  with find-or-create (reuse `normalize_vendor` + `spoolman.get_vendors()` +
  `spoolman.create_vendor({"name": vendor_name})`; mirror the wizard's `_ensure_vendor`
  pattern; build the vendor index ONCE per apply call, and cache newly-created ids to avoid
  duplicates within the run). Then include `vendor_id` in the filament PATCH (alongside the
  other native/extra fields, or as part of the same `update_filament` payload). Report
  `vendor` in `fields_written`.
- Keep it idempotent/safe: never create a duplicate vendor for a name that already exists
  (normalized match wins); skip when keep-mine or unchanged.

## Verification

- `cd backend && pytest` — tests:
  - matches: a Spoolman "Prusa" filament matched (via alias) to an OpenTag "Prusament" brand
    yields a `vendor` field row with `spoolman_value="Prusa"`, `opentag_value="Prusament"`;
    a same-vendor match yields NO vendor row.
  - apply: choosing the OpenTag vendor resolves an EXISTING Spoolman vendor by normalized name
    (no duplicate created) and PATCHes the filament `vendor_id`; when the vendor doesn't exist
    it creates it once and uses the new id; keep-mine leaves the vendor untouched.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Reason through: Prusa→Prusament alias match now shows a Manufacturer row (default
  Prusament); applying reassigns the filament to the Prusament vendor; the badge/diff logic
  reflects vendor as a difference too.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: OpenTag cleanup can reassign the Spoolman vendor to the matched
   OpenTag brand (find-or-create vendor + `vendor_id`), shown as a reviewable field only when
   the names differ.
3. Non-interactive subagent run: when pytest + build pass, stage ONLY the files this task
   touched (incl. prompt move + docs) and commit on `dev` with one `feat:` message. Never
   `git add -A`. Never push.
