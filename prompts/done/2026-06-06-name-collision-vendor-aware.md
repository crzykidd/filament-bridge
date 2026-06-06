---
name: 2026-06-06-name-collision-vendor-aware
status: completed
created: 2026-06-06
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-06-06
result: _compute_name_collisions now keys on (vendor, name); 3 new unit tests; 377/377 pass
---

# Task: Make wizard "name collision" detection vendor-aware (stop flagging same-name different-vendor)

The wizard Preview "Name collisions" flag matches by NAME ONLY, so an incoming filament
"beige" from one vendor gets flagged as colliding with an already-existing "Beige" from a
DIFFERENT vendor — a false positive. The bridge's matcher keys on vendor+name+color, so the
collision check should at least be vendor-aware: only flag when the SAME vendor+name
already exists (a genuine potential duplicate), not across different vendors.

## Before you start

- Read `CLAUDE.md`. Work on `dev`, `fix:` prefix, no `Co-authored-by:`.
- The flag is informational (not blocking), but it's noise. This is a precision fix.

## Current code (verify, then change)

`backend/app/api/wizard.py` `_compute_name_collisions` (~1257-1279):
```python
existing: dict[str, str] = {normalize_name(f.name): f.id for f in fdb_filaments}
incoming: dict[str, list[_FilamentPlanItem]] = {}
for item in plan.filament_items:
    if item.action == "create" and not item.error and item.fdb_payload:
        norm = normalize_name(item.fdb_payload.get("name", "") or "")
        if norm:
            incoming.setdefault(norm, []).append(item)
...
    vs_existing = norm_name in existing
    intra_batch = len(items) > 1
```
Keys are name-only → cross-vendor same-name collides.

## What to do

Make the collision key `(normalize_vendor(vendor), normalize_name(name))`:

- `existing`: build from `fdb_filaments` keyed by
  `(normalize_vendor(f.vendor), normalize_name(f.name))` → `f.id`. (`FDBFilament.vendor` is
  the vendor name string; `normalize_vendor` is in `backend/app/core/matcher.py`, already
  imported or import it.)
- `incoming`: key each create item by
  `(normalize_vendor(item.fdb_payload.get("vendor")), normalize_name(name))`. The vendor in
  the FDB payload is the vendor name string (planner sets it from `sm.vendor.name`).
- `vs_existing` / `intra_batch` then operate on the (vendor, name) key, so a "beige" from
  vendor A no longer collides with a "beige" from vendor B. Same vendor+name (true
  duplicate, e.g. a missed match or a same-line variant) still flags.
- `NameCollisionEntry` keeps `normalized_name` for display; populate it from the name part
  of the key. Optional but nice: include the vendor in the entry so the card can read
  "beige (ELEGOO)" — only if `NameCollisionEntry` already has/easily takes a vendor field;
  don't expand the frontend if it adds churn. Keep `existing_fdb_filament_id` from the
  matched (vendor, name) key.

## Verification

- `cd backend && pytest` — add tests:
  - two incoming "Beige" filaments from DIFFERENT vendors → NO collision; one of them vs an
    existing FDB "Beige" of a different vendor → NO `vs_existing`.
  - same vendor+name as an existing FDB filament → `vs_existing=True`.
  - two incoming same vendor+name in one batch → `intra_batch=True`.
- `cd frontend && npx tsc --noEmit && npm run build` only if you touch the frontend.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: name-collision detection is vendor-aware (keyed on vendor+name) to
   stop false positives across vendors — only if non-obvious.
3. Non-interactive subagent run: when pytest (+ any build) passes, stage ONLY the files
   this task touched (incl. prompt move + docs) and commit on `dev` with one `fix:`
   message. Never `git add -A`. Never push.
