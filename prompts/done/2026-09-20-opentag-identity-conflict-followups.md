---
name: 2026-09-20-opentag-identity-conflict-followups
status: completed          # pending | completed | failed
created: 2026-09-20
model: sonnet
completed: 2026-09-20
result: >
  Shipped all three fixes in one pass: shared `_auto_resolve_converged_conflicts` helper wired
  into all five cross_system convergence points (#91); `_sync_opentag_identity` now compares the
  surviving side's baseline before treating a clear as propagatable, routing the clear-plus-relink
  race through `resolve_sync_action` instead (#93); added `_apply_opentag_identity` +
  `OPENTAG_IDENTITY_FIELD` so the identity conflict has an apply path (#94). 12 new backend tests
  (1508 -> 1520 passing), ruff clean, docs (prd.md, sync-model.md, conflicts.md, decisions.md +
  regenerated index) and CHANGELOG updated in the same pass. Not committed — left for the
  orchestrating session to review and commit.
---

# Task: #91 + #93 + #94 — OpenPrintTag identity conflict follow-ups

Three related fixes to the OpenPrintTag identity conflict path, all in the same pass and the
same conflict machinery. Ship them as ONE commit.

- **#91** — a `cross_system` conflict whose divergence later vanishes is never auto-resolved, so
  it lingers in the queue AND blocks future conflicts for that pair (`_has_open_conflict` dedup).
  The audit below shows this is not identity-specific: **every** `cross_system` producer has the
  same hole, so the fix is a **shared convergence check**, not an identity-pass special case.
- **#93** — the #89 clear-propagation routes on "did this side ever hold a value" alone and never
  compares the *surviving* side to its own baseline, so a clear on one side silently blanks a
  simultaneous re-link on the other, with no conflict.
- **#94** — `apply_cross_system_conflict` has no branch for `field_name == "OpenPrintTag
  identity"`, so resolving that conflict in the UI returns 422. Without this, #91 and #93 both
  end in "queue a conflict for a human" that the human cannot action.

## Before you start

- Read `CLAUDE.md` in full. The load-bearing rules for this task:
  - **Conflicts are never auto-resolved.** The narrow, already-established exception is
    housekeeping: closing a conflict row whose *triggering condition no longer applies*
    (`auto_stale_purge`, `auto_resolved_reappeared`, `resolved_not_imported`). See the
    clarification at `docs/prd.md:401`. **Only ever close a conflict whose two current values
    have been OBSERVED equal. Never pick a winner for a real divergence.**
  - **The `settings{}` scoped exception**: `merge_filament_settings()` /
    `remove_filament_settings_keys()` are the ONLY permitted writers to the FDB filament
    `settings{}` bag, and ONLY for `openprinttag_slug` / `openprinttag_uuid`.
  - **After any propagation, refresh BOTH side snapshots to the post-write agreed values** —
    otherwise the change is re-detected next cycle (ping-pong).
- Read the three issues: `gh issue view 91`, `gh issue view 93`, `gh issue view 94`.
- Read `docs/decisions.md`'s **2026-09-18** entry (the #89/#90 design, incl. the "known
  limitation" bullet corrected 2026-09-20 — that limitation IS #93).
- Read `backend/app/core/engine.py::_sync_opentag_identity` (~line 4298) and its docstring table
  in full before changing anything. Read `backend/tests/test_engine_opentag_identity.py` (644
  lines, 15 tests) for the fixture conventions you must match.
- Read `backend/app/core/conflict_apply.py::apply_cross_system_conflict` (~647) and
  `_apply_opentag_field` (~the OPENTAG_EXTRA_FIELDS branch) — the latter is the template for #94.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files this plan
needs to modify. If any have uncommitted changes, list them and ask the user before touching
them. Surface unrelated dirty files once as awareness; don't block. This file (the handoff
prompt) is exempt.

---

## Part A — #91: shared converged-conflict auto-resolution

### The audit (already done — this is the finding, don't redo it)

Every `cross_system` producer has a convergence branch that refreshes baselines and `continue`s
**without touching an open conflict** for that entity+field:

| Pass | `engine.py` | Convergence branch |
|---|---|---|
| Material-prop scalars/temps | ~1711 | `if sm_changed and fdb_changed and sm_now == fdb_now:` → `_store(...)`, `continue` |
| OpenTag extra fields | ~2020 | same shape |
| Lifecycle | ~3718 | `both_changed_converged` → the whole conflict block is skipped |
| Location | ~3878 | `location_both_converged` (added by #90) → same |
| OpenTag identity | ~4648 | both-empty / both-set-equal branches → `continue` |

Identity is only special in that the **engine itself** can now converge it (via #89's clear
propagation), which is what makes the stale row reachable without user action. The others are
reachable when a user converges both sides upstream by hand.

⇒ **The fix is a shared helper, wired into all five convergence points.**

### A1 — the helper

Add next to `_has_open_conflict` in `engine.py` (mirror its filter shape exactly):

```python
def _auto_resolve_converged_conflicts(
    db: Session,
    cycle_id: str,
    entity_type: str,
    field_name: str,
    *,
    spoolman_id: int | None = None,
    fdb_filament_id: str | None = None,
    fdb_spool_id: str | None = None,
    converged_value: Any = None,
) -> int:
```

- Query open (`resolved_at is None`) `Conflict` rows with `conflict_type == "cross_system"`,
  matching `entity_type`, `field_name`, and whichever ids were passed (same `if x is not None`
  filter pattern `_has_open_conflict` uses).
- For each: `resolved_at = now(utc)`, `resolution = "auto_resolved_converged"`, and
  `resolved_value = json.dumps(converged_value)` when `converged_value is not None` (leave
  `None` otherwise — a converged-to-empty identity legitimately has no value).
- Emit one `_log(db, cycle_id, "auto", "info", entity_type, ...)` row per resolved conflict with
  `field_name=field_name` and an `error_message` saying the divergence converged (mirror the
  `auto_resolved_reappeared` log at ~3423 for tone/shape).
- Return the count.
- **Callers guard with `if not dry_run:`** — the helper itself never checks dry-run (keep it
  consistent with the surrounding helpers; the dry run must not mutate the DB).
- Docstring must state the narrow contract: *only* call this where the pass has actually
  observed both current values and found them equal; it closes housekeeping rows, it never
  picks a winner.

### A2 — call sites

Add a call at each convergence point. Keep existing control flow intact — do not restructure.

1. **Material-prop pass (~1711)** — inside the `sm_changed and fdb_changed and sm_now == fdb_now`
   branch, before `_store(...)`: `entity_type="filament"`, `field_name=label`,
   `spoolman_id=m.spoolman_filament_id`, `fdb_filament_id=m.filamentdb_id`,
   `converged_value=sm_now`.
2. **OpenTag extra fields (~2020)** — same, with `field_name=ef.label`.
3. **Lifecycle (~3718)** — the conflict block is guarded by
   `if (lifecycle_sm_changed or lifecycle_fdb_changed) and not both_changed_converged:`. Add an
   `elif both_changed_converged and not dry_run:` (or an equivalent that does not disturb the
   existing branch) calling the helper with `entity_type="spool"`, `field_name="lifecycle"`,
   `spoolman_id=sm_spool.id`, `fdb_spool_id=fdb_spool.id`, `converged_value=sm_archived_now`.
4. **Location (~3878)** — mirror of 3, `field_name="location"`,
   `converged_value=sm_location_now` (the RAW value, matching what the conflict rows store).
5. **Identity pass (~4600s)** — see Part B; the identity call sites are:
   - the `not sm_has and not fdb_has` branch (converged to empty — `converged_value=None`),
   - the both-set-equal branch (`converged_value=sm_uuid`),
   - the success path of each of `_push_sm_to_fdb`, `_push_fdb_to_sm`, `_clear_sm_side`,
     `_clear_fdb_side` (right after `_store_baseline`, so a conflict closes in the same cycle the
     pass converges the pair rather than lagging one cycle). Use the value that was just written
     (`None` for the two clear helpers).

**Do NOT** call the helper from the `QUEUE_CONFLICT` path or from any branch where the two
current values differ.

---

## Part B — #93: a clear must not beat a simultaneous re-link

In `_sync_opentag_identity`, the two clear branches currently key only on `fdb_had` / `sm_had`
("did this side ever hold a value") plus "is the other side non-empty". Neither consults the
**surviving** side's own baseline, so a clear here + a re-link there blanks the new value with no
conflict.

### B1 — capture the baseline VALUES, not just the booleans

Where `sm_had` / `fdb_had` are computed, also keep the baseline strings:

```python
sm_base = (sm_snap or {}).get("_opt_uuid") or ""
fdb_base = (fdb_snap or {}).get("_opt_uuid") or ""
sm_had = bool(sm_base)
fdb_had = bool(fdb_base)
```

### B2 — extract the divergence resolution into a shared nested helper

The both-set divergence block at the bottom of the pass (`resolve_sync_action` → NOOP /
QUEUE_CONFLICT / PUSH_*) must be reusable from the clear branches. Extract it as a nested
`async def _resolve_divergence(m, sm_slug, sm_uuid, fdb_slug, fdb_uuid, label_name, *, reason: str,
refresh_baselines: bool) -> None` and have the existing both-set path call it with
`reason="both sides have a different OpenPrintTag identity"` and `refresh_baselines=True`
(today's behavior, unchanged — including the dedup via `_has_open_conflict` and the dry-run
preview row).

### B3 — route the clear branches through it when the surviving side also changed

```
if sm_has and not fdb_has:
    if fdb_had:
        if (sm_uuid or "") != sm_base:
            # FDB was unlinked AND Spoolman was re-linked in the same interval —
            # two opposing actions, not a clear to propagate.
            await _resolve_divergence(..., reason="OpenPrintTag link removed in Filament DB "
                                                  "while Spoolman was re-linked",
                                      refresh_baselines=False)
            continue
        if allow_fdb_to_sm:                 # unchanged #89 behavior
            await _clear_sm_side(...)
        continue
    ...
```

and the mirror for `fdb_has and not sm_has` / `sm_had` (compare `(fdb_uuid or "") != fdb_base`,
reason "OpenPrintTag link removed in Spoolman while Filament DB was re-linked").

### B4 — `refresh_baselines=False` on these paths is LOAD-BEARING. Comment it.

Explain in a comment (and in the decisions entry) why:

- If the conflict path refreshed baselines to the *observed* values, the cleared side's baseline
  would become empty → next cycle reads "never linked" → the pass would **fill** it, silently
  resolving the conflict it just queued.
- If it refreshed only the surviving side, that side's baseline would match its current value →
  next cycle reads "surviving side unchanged" → the pass would **propagate the clear**, blanking
  the value — the exact bug #93 fixes.
- Leaving both baselines untouched keeps the pair stably on the conflict path every cycle
  (deduped by `_has_open_conflict`, so nothing accumulates) until a human resolves it via #94's
  new apply path, which writes both sides and refreshes both baselines itself.

### B5 — note the one intentional behavior change

Routing through `resolve_sync_action` replaces the explicit `allow_fdb_to_sm` / `allow_sm_to_fdb`
gate on *this sub-case only*. Under a one-way direction the resolver returns the push in the
configured source direction, so e.g. `direction=spoolman_to_filamentdb` with FDB cleared + SM
re-linked now pushes SM's new identity to FDB instead of doing nothing. That is consistent with
the direction setting and is an improvement, but **call it out in the decisions entry**. The
plain one-sided-clear case keeps its existing `allow_*` gate and behavior exactly.

---

## Part C — #94: the missing identity apply path

`apply_cross_system_conflict` (`conflict_apply.py:647`) dispatches on `conflict.field_name` and
has no branch for `"OpenPrintTag identity"`, so it falls through to `UnsupportedConflictField` →
`api/conflicts.py` → **422**. Affects both the single resolve and the bulk-resolve path (~894).

1. **Add a shared constant.** The label is currently a bare literal in the engine
   (`field_label = "OpenPrintTag identity"`). Define `OPENTAG_IDENTITY_FIELD = "OpenPrintTag
   identity"` in `backend/app/core/fields.py` and use it in BOTH `engine.py` and
   `conflict_apply.py`. Do not change the string value — existing conflict rows carry it.
2. **Add `_apply_opentag_identity(...)`**, modelled on `_apply_opentag_field`:
   - `sm_fil_id = conflict.spoolman_id`, `fdb_fil_id = conflict.filamentdb_filament_id`.
   - Chosen uuid via `_resolve_value(conflict, resolution, manual_value)`.
   - The conflict row stores only the **uuid** on each side, so fetch both sides live
     (`spoolman.get_filament` / `filamentdb.get_filament`) to recover the **slug that accompanies
     the chosen uuid** — the pair must stay consistent. For `manual`, carry a slug only if that
     side's uuid matches the manual value; otherwise write the uuid alone rather than inventing a
     slug.
   - **Write both sides idempotently:**
     - Chosen value non-empty → Spoolman `update_filament(sm_fil_id, {"extra": {slug_field:
       encode_extra_value(slug), uuid_field: encode_extra_value(uuid)}})` (omit the slug key when
       there is no slug), and FDB via `filamentdb.merge_filament_settings(fdb_fil_id, {...})` —
       the scoped exception, those two keys only.
     - Chosen value empty/None → blank both SM extras (`encode_extra_value("")`, as
       `_clear_sm_side` does) and `filamentdb.remove_filament_settings_keys(fdb_fil_id,
       ["openprinttag_slug", "openprinttag_uuid"])`.
   - **Refresh BOTH baselines** with `_merge_snapshot(...)` on keys `_opt_uuid` / `_opt_slug`
     (source `"spoolman"` entity_id `str(sm_fil_id)`; source `"filamentdb"` entity_id
     `fdb_fil_id`) to the converged value — same shape the engine's `_store_baseline` writes, so
     the next cycle sees agreement and a later one-sided clear still reads as "had a value".
   - `_log(...)` a `conflict_apply` row and `_resolve_conflict_row(conflict, resolution, value,
     db)`, exactly like the neighbouring appliers.
   - Let upstream write failures propagate (the endpoint maps them to 502 and leaves the conflict
     open) — do not swallow them.
3. Wire it into the dispatcher next to the other named fields.

---

## Tests

Backend only; no frontend change is expected in this task (verify that — if the Conflicts UI
needs a display string for the new `auto_resolved_converged` resolution, add it; `grep -rn
"auto_resolved_reappeared" frontend/src` returned nothing, so most likely it does not).

**`backend/tests/test_engine_opentag_identity.py`** — match the existing fixture helpers
(`_seed_identity_baseline`, `_get_identity_baseline`, `_fake_spoolman`, `_fake_fdb`,
`_seed_matprop`):

- `#93` — FDB cleared + SM re-linked to a NEW uuid → a `cross_system` conflict is queued,
  `spoolman.update_filament` is **NOT** called (nothing blanked), and **neither baseline moved**.
- `#93` — mirror: SM cleared + FDB re-linked → conflict queued,
  `filamentdb.remove_filament_settings_keys` NOT called, baselines unmoved.
- `#93` — stability: run the same cycle twice → still exactly one conflict (deduped), still no
  writes, baselines still unmoved.
- `#93` regression guard for #89 — the plain one-sided clear (surviving side unchanged) still
  propagates. (Existing tests cover this; assert explicitly that they still pass rather than
  weakening them.)
- `#91` — an open identity conflict is auto-resolved (`resolution == "auto_resolved_converged"`,
  `resolved_at` set) once the pass observes both sides equal, and once it observes both empty
  after a clear propagated.
- `#91` — a still-diverging pair's conflict is **NOT** auto-resolved.
- `#91` — dry run does not resolve anything.
- `#91` — after the auto-resolve, a NEW divergence on that pair queues a fresh conflict (proves
  the `_has_open_conflict` block is lifted).

**At least one non-identity `#91` test** — pick the lifecycle or location pass (whichever has the
cheaper existing fixture; see `test_engine_*` for lifecycle/location coverage) and assert a
converged both-changed pair auto-resolves its open conflict. This is the point of making the fix
shared; cover it.

**`#94`** — in the conflict-apply suite (find the existing one, e.g.
`grep -rln apply_cross_system_conflict backend/tests`): resolve-to-spoolman, resolve-to-filamentdb
and resolve-to-empty (the removal path), each asserting the Spoolman write, the FDB write via the
correct scoped helper, both refreshed baselines, and the resolved conflict row.

**Run before proposing the commit:**

```bash
cd backend && .venv/bin/python -m pytest
.venv/bin/python -m ruff check backend/       # from the repo root
cd frontend && npx vitest run && npx tsc --noEmit   # only if you touched frontend/
```

All must be green. Report the test count before/after.

## Docs (same commit — non-negotiable)

- **`docs/prd.md:401`** — the "Clarification — conflicts are never auto-resolved" paragraph lists
  the housekeeping paths by name. Add `auto_resolved_converged` and describe it in one sentence
  (a conflict row whose two values have since been observed equal; no value is chosen).
- **`docs/sync-model.md`** — document the shared convergence check in the pass ordering /
  housekeeping section (near the `resolved_not_imported` note at ~161).
- **`docs/conflicts.md`** — add the new resolution string to whatever list the `auto_stale_purge`
  note at ~106 belongs to, and state that an identity conflict can now be resolved from the UI
  (#94).
- **`docs/decisions.md`** — ONE dated `## 2026-09-20` entry covering all three: the #91 audit
  finding (the table above — why the fix is shared, not identity-local), the #93
  `refresh_baselines=False` rationale from B4, the B5 direction-gating behavior change, and the
  #94 apply path. Then **regenerate the index**: `python scripts/gen-decisions-index.py` (add the
  new heading to that script's `CATEGORIES` if it needs one).
- **`CHANGELOG.md`** — add entries under `## [Unreleased]` naming each issue (`Fixes #91`,
  `Fixes #93`, `Fixes #94`) so the issue ↔ release mapping is visible in the release notes.

## Conventions to honor

- Match the surrounding code's style: nested async helpers inside the pass, the same `_log` /
  `result.*` accounting, the same dry-run preview-row shape (`action`, `entity_type`,
  `direction`, `label`, `field`, `old`, `new`, `reason`, `spoolman_id`, `fdb_filament_id`,
  `fdb_spool_id`).
- Every new branch must be **dry-run aware**: no DB mutation, no upstream write, a preview row
  instead.
- Keep the `_sync_opentag_identity` docstring table accurate — it is the spec for this pass.
  Update it for the new clear-plus-relink row and the convergence auto-resolve.
- Do not touch `settings{}` outside the two scoped helpers.
- Do not widen scope: only #91, #93, #94. No drive-by refactors of the other passes beyond
  adding the single helper call at each convergence point.

## When done

1. Update this file's frontmatter: `status`, `completed` (2026-09-20 or the actual date),
   `result` (one line).
2. `git mv` this file into `prompts/done/`.
3. Record the decisions in `docs/decisions.md` as specified above (+ regenerate the index).
4. Propose ONE commit covering everything (code + tests + docs + the prompt move). Present the
   file list and the message, and ask before committing. The message is a conventional-commit
   `fix:` one-liner with a body ending in the three closing trailers:

   ```
   Fixes #91
   Fixes #93
   Fixes #94
   ```

   No `Co-authored-by:` trailer. Commit on `dev`. **Never push** — the user pushes.
