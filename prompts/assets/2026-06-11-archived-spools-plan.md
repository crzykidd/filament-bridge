# Agreed implementation plan — import archived/empty spools as retired FDB spools

Companion to `prompts/2026-06-11-import-archived-empty-spools.md`. Signed off 2026-06-11.
Locked decisions: **O1 = import archived-non-empty as retired** (archived ⇒ retired,
empty gate applies only to empties). **O3 = use `remaining <= 0.0`** at all empty-gate
sites (proven case has negative remaining). O2 (no un-archive flip-back) accepted +
documented.

## Root cause (proven, do not re-investigate)
`if not s.archived` at planner.py:316 drops archived spools BEFORE the
`include_empty_spools` gate (planner.py:458) — so archived/used-up spools never import even
with `never_import_empties=false`. Fix: route archived spools through the empty gate, import
as RETIRED FDB spools. Engine already guards mapped archived spools (engine.py:2380–2404).

## 1. `if not s.archived` sites — change/keep
| # | Location | Role | Decision |
|---|---|---|---|
| A | planner.py:316 `sm_spools_by_filament` | IMPORT gate (the bug) | **CHANGE** — remove the archived filter; append every spool |
| B | planner.py:458 empty gate | EMPTY gate | keep; change `== 0.0` → `<= 0.0`; new `_SpoolPlanItem` carries `retired` |
| C | wizard.py:464 `spools_per_filament` (variants master heuristic) | HEURISTIC | **KEEP active-only** |
| D | wizard.py:611–615 `spool_ids_per_filament` (variances) | DISPLAY of importable ids | **CHANGE** — drop archived clause; keep `<=0` empty clause |
| E | wizard.py:618–621 `spools_per_filament` (variances heuristic) | HEURISTIC | **KEEP active-only** |
| F | wizard.py:291 xref map build | xref recognition | **CHANGE** — include archived (keep `filament is None` guard) |
| G | wizard.py:397 `wizard_weights` legacy preview | DISPLAY | **CHANGE** — include archived |
| H | wizard.py:1129 generic_container parent scan | parent recovery | **CHANGE** — include archived |
| I | wizard.py:1880 `_compute_empty_active` | DISPLAY/COUNT | **CHANGE** — bucket empties incl. archived; add `archived` flag |
| J | engine.py:2249 `sm_spools` active-only | GUARDRAIL | **KEEP** (anti-ping-pong) |
| K | engine.py:2795 cost helper | HEURISTIC | **KEEP active-only** |
| L | dryrun.py:74 `active_sm_spools` | GUARDRAIL | **KEEP**; verify dryrun:206 passes full `sm_spools` to planner so archived show as `create` preview |

## 2. Gate semantics
- empty = `(remaining_weight or 0.0) <= 0.0`.
- `never_import_empties=false` → import all incl. empties + archived (archived ⇒ retired).
- `never_import_empties=true` → skip empties (archived or active).
- archived non-empty → imports as retired (O1).

## 3. Retired representation
- `_SpoolPlanItem.retired: bool = False` (planner.py:172); set
  `retired=bool(getattr(sm_spool,"archived",False))` in Phase C (~line 506). Weight via normal
  `spoolman_to_fdb_gross` — no special-casing.
- wizard.py:1608 `spool_payload["retired"] = spool_item.retired`. FDBSpool.retired exists
  (schema:47), round-trips; bridge currently never sets it (the resurrection bug).
- SpoolMapping create unchanged (this is what makes it show in Synced Records).
- `_seed_snapshots` (wizard.py:1638): change hardcoded `"retired": False` →
  `spool_item.retired` so FDB baseline matches.

## 4. Engine guardrails (no engine code change)
Retired imported spool protected by: mapped-pair archived branch (engine.py:2380 → skip, no
write); new-SM-spool detection iterates active only (2855); new-FDB-spool detection sees it
in `mapped_fdb_spool_ids` → continue (2895). Differ has no `retired` field and the pair
never reaches the diff → no change. `retired`/`archived` is intentionally NOT a synced field
(set once at import). Document in decisions.md + sync-model.md. O2: un-archive later does not
flip FDB retired back — accepted, documented.

## 5. Transparency
- `EmptyActiveEntry.archived: bool` (api.py:586); `_compute_empty_active` emits entries for
  `remaining<=0 OR archived` with the flag.
- Frontend StepNPreview.tsx (~190–198): render "Archived → imports as retired" tag; update copy.
- Execute spool-create `res.add(..., "created", detail=...)` (wizard.py:1642): when
  `spool_item.retired`, detail = `f"imported as retired (archived in Spoolman, spool #{id})"`.
  Also set retired detail on the preview plan row (wizard.py:2158). Fixes the "no details" complaint.

## 6. Tests
Backend (fixtures mirror SM filament 63 / spool 65, archived, used 1047.98 > initial 1000 →
remaining ≤ 0; test both ≤0 and ==0):
1. planner imports archived empty spool → plan item `create`, `retired=True` (include_empty=True)
2. planner skips empty when never_import_empties (include_empty=False) — archived & active empty
3. active empty still gated (retired=False when imported; skipped when off)
4. execute: FDB create_spool called with retired=True; SpoolMapping exists; filament in
   build_mapping_rows; log/record detail contains "retired"
5. execute never_import_empties=true → no create_spool/SpoolMapping for #65
6. engine cycle: updated==0, conflicts==0, one skipped(archived); second cycle stable (no ping-pong)
7. `_compute_empty_active` includes archived entry with archived=True
8. (optional) master heuristic counts active only
Frontend: 9. StepNPreview renders "imports as retired" for archived empty entry.
Gates: backend pytest + ruff; frontend tsc + npm test.

## Docs (same commit)
wizard.md (archived→retired + empty gate), configuration.md (never_import_empties governs
archived too), spoolman-writes.md / FDB-writes (now set `retired` on create), decisions.md
(archived⇒retired, not a synced field, O1/O2 rationale).
