# Decision record

## 2026-06-05 — Conflicts page: client-side type filter

`classifyConflict` derives a `ConflictType` bucket purely from `field_name` and `spoolman_id`
fields already present on `ConflictResponse` — no API or schema changes. `new_spool` direction
is disambiguated by `spoolman_id != null` (Spoolman-only spool) vs null (FDB-only spool), per
the engine's existing behavior. The filter bar appears only when two or more types are present,
so a single-type list is never cluttered with an unnecessary UI element.

## 2026-06-05 — Upstream deletion detection → conflict queue

### Design

When a mapped record disappears from an upstream fetch, the bridge now queues a
`Conflict` row with `field_name = "__record_deleted__"` (sentinel constant
`DELETION_FIELD` in `app/models/conflict.py`) instead of logging a skip/error and
continuing. This keeps the "conflicts are never auto-resolved" hard rule and gives the
user an explicit UI action to take.

**Archived vs deleted (Spoolman side):** `sm_all_ids` (set of all spool ids returned
by Spoolman, including archived ones) is built each cycle. An id absent from
`sm_all_ids` is gone entirely → deletion conflict. An id present but not in the
active (non-archived) dict → skip as before. This preserves the existing archived-spool
skip behavior.

**Dedup:** `_queue_deletion_conflict` checks for an existing open conflict with the
same sentinel `field_name`, `spoolman_id`, and `filamentdb_spool_id` before inserting.
This prevents a new conflict row from accumulating every cycle until the user resolves.

**Value encoding:** the surviving side's value carries
`{"exists": true, "deleted_side": "<spoolman|filamentdb>"}`. The deleted side is
`null`. The frontend keys off `deleted_side` to render a human-readable explanation
instead of a raw value diff.

**Dashboard / Synced Records:** `build_mapping_rows` already flips a row to
`status="conflict"` when any open conflict references its spool ids. No changes to
`mappings.py` were needed — queueing the deletion conflict is sufficient.

### Resolution cleanup

When `resolve_conflict` or `bulk_resolve` marks a `DELETION_FIELD` conflict as
resolved, `_cleanup_orphaned_mapping` deletes the `SpoolMapping` row and both `Snapshot`
rows for that pair from bridge-local SQLite. This is bridge-local state only — no
upstream writes. The mapping disappears from Synced Records and the Dashboard count
corrects itself on the next page load.

**Upstream re-create is Phase 2.** If the user wants to restore the deleted upstream
record and re-link it, that is a separate future workflow. The conflict router never
writes to Spoolman or Filament DB (existing hard rule; see "resolve = record, apply
next cycle" philosophy above).

## 2026-06-04 — variant_line_keywords user setting + Standalone "Move to existing group"

### variant_line_keywords — user-configurable finish/line keyword lexicon

`matcher.py`'s `extract_finish_line` and `sm_variant_cluster_key` now accept an optional
`keywords: list[str]` parameter. When provided, each keyword is matched whole-word
case-insensitively (`\bkeyword\b`); the first match becomes the finish token. When `keywords`
is `None`, the original `_FINISH_PATTERNS` regex lexicon is used (backward-compatible fallback
for tests and any non-wizard caller).

**Resolution:** env var `VARIANT_LINE_KEYWORDS` (comma-separated) seeds the default with the
same tokens as `_FINISH_PATTERNS` plus `rapid`. At runtime, `get_config_value(db, "variant_line_keywords", settings.variant_line_keywords)` lets the UI override the env default without a restart. `wizard_variances` and `wizard_variants` both call `_resolve_variant_keywords(db)` and pass the result to every `sm_variant_cluster_key` / `extract_finish_line` call. The matcher functions remain pure (no DB import). `ConfigResponse` / `ConfigUpdateRequest` expose `variant_line_keywords`; `Settings.tsx` adds an editor text field.

### Standalone rows gain "Move to existing group"

The Standalone section in `StepVariances.tsx` previously only offered multi-select "Group as
variants" (new group only). Each standalone row now also shows a **"Move to…"** dropdown
(via `movingStandaloneId` state + `moveFromStandalone` / `standaloneTargetOptions` helpers)
listing all existing non-empty auto/extra groups plus "New group". After a move the row
disappears from Standalone and joins the target group; `handleSave` is driven by membership
state so no special handling is needed.

## 2026-06-04 — Wizard per-member actions + finish-line auto-split (Part A/B)

Extends the 2026-06-04 D1–D4 redesign. Source of truth for D1–D4 remains that entry;
this section records the Part A (per-member actions) and Part B (finish-line split) additions.

### Part A — Per-member labeled actions replace the checkbox

`StepVariances.tsx` grouped-filament rows now show three labeled buttons per member instead of
a bare always-checked disabled checkbox:

- **Move to…** — dropdown listing all other auto/extra groups and "New group"; removes from source,
  adds to target (with master promotion if the moving member was master).
- **Standalone** — removes from group; member appears in the standalone list with its own tare.
- **Ignore** — calls `POST /wizard/matches/{sm_filament_id}/skip`, which sets `action: "skip"` in
  `wizard_match_decisions`, then removes from the group. Uses `_included_sm_ids()` as the single gate,
  so the change flows to variances/weights/preview/execute for free. No second exclusion set.

The `Ignore` button is also present on standalone filament rows and extra-group (manually grouped) rows.
Master radio button is unchanged. Groups dissolved to 0 members are hidden (no empty card).

`ignoreErr` is surfaced as a red text line above the Save/Back row.

### Part B — Finish-line auto-split extends D1 grouping key to 3-tuple

**Q1 resolved.** `sm_variant_cluster_key` in `matcher.py` now returns a 3-tuple
`(normalize_vendor, normalize_name(material), finish)` where `finish` is the output of
`extract_finish_line(name, material)`.

`extract_finish_line` uses a word-boundary-aware regex lexicon (ordered most-specific first):
`glow-in-the-dark / GITD`, `carbon fiber / CF`, `rainbow / multicolor`, `high-speed / HS`,
`metallic`, `marble`, `wood`, `matte`, `satin`, `silk`. Returns `""` for standard/unrecognized.

Effect: `ELEGOO PLA Red` and `ELEGOO PLA Silk Red` now get different cluster keys (`""` vs `"silk"`),
so they land in separate variant groups — preventing Silk from inheriting PLA print settings via the
parent. D2's `suggest_exclude` signal survives as a second-line safeguard for finish tokens not in the
lexicon. The lexicon is a closed set; user-driven move/standalone actions are the escape hatch.

FDB parent map keying in `wizard_variances` updated to 3-tuple `(vendor_norm, material_norm, finish_norm)`
so existing Silk FDB parents match Silk SM groups (not standard PLA parents).

`VariancesGroupRow` gains `finish: str | None` (shown in the group header as a violet pill).
Frontend `VariancesGroupRow` interface updated to match.

## 2026-06-04 — Wizard variant-resolution redesign: D1 grouping key, D2 suggest-exclude, D3 FDB-parent attach, D4 empty-spool toggle

Implements `docs/wizard-redesign.md` decisions D1–D4 in full. Source of truth is that spec;
this entry records the settled contract. See the "Part A/B" entry above for the Q1 resolution
(finish-line split) and per-member action redesign that followed.

### D1 — Grouping key is `(vendor, material)` — drop base_name (initial pass)

`sm_variant_cluster_key` in `matcher.py` returned a 2-tuple `(normalize_vendor, normalize_name(material))`.
The old 3-tuple included `base_name = strip_color_and_words(name, color_hex)`, which caused filaments
whose name IS a color word (e.g. "Brown", "Beige") to produce different base_names and never cluster.

All callers updated to unpack 2-tuples; extended to 3-tuples by Part B above.
Group display `base_name` is now `normalize_name("{vendor} {material}")` — consistent across all paths.

**Q1 simplification (initial pass, since superseded):** finish/line tokens (PLA Matte / Silk / PLA-CF)
were NOT parsed out in this pass. Q1 is now resolved by the Part B finish-line split above.

### D2 — Per-member exclude, pre-flagged by `sm_prop_conflicts`

`VariancesFilament` gains `suggest_exclude: bool = False`. Set to `True` for non-master members where
`sm_prop_conflicts(master, member)` returns ≥1 mismatch (density, extruder_temp, bed_temp, etc.).
Conflicts are still surfaced, never auto-resolved. The flag is a *hint* only — the user remains in
control via the membership checkboxes in `StepVariances.tsx`.

Pre-suggested-excluded members start unchecked in the initial `groupMembership` state (frontend).

Standalones also gain checkbox select + "Group as variants" action: select 2+ standalone filaments
and click the button to create an editable extra group (pick master via radio). This is the only
path to manually group filaments that the auto-clustering didn't detect.

### D3 — Load FDB state; resolve each incoming color as Attach / Create

`wizard_variances` now also loads `filamentdb.get_filaments()` and builds a
`(vendor_norm, material_norm) → FilamentRef` map of existing FDB parent lines (filaments with
`hasVariants=True` or with children pointing to them via `parentId`).

`VariancesGroupRow` gains `existing_fdb_parent: FilamentRef | None`. When set, the frontend offers
a per-group choice: **Attach to existing FDB parent** (default) vs **Create new parent**.

`SMVariantDecision` gains `existing_fdb_parent_id: str | None = None`. Semantics:
- **None** → SM-keyed master-promote (unchanged behavior: master becomes the FDB parent).
- **set** → ALL members (including the "master") are created with `parentId = existing_fdb_parent_id`;
  no new parent is created. The existing FDB parent is **never modified or deleted** — only `parentId`
  is written on newly-created variants.

New helper `_build_attach_parent_for_sm(decisions) → {sm_id: existing_fdb_parent_id}` in `wizard.py`.
In `_execute_spoolman_to_fdb` Pass 1: attach-group masters get `parentId` injected into the create
payload; `master_map[master_sm_id]` is set to `existing_fdb_parent_id` (not the newly-created FDB id),
so Pass 2 variants correctly receive `parentId = existing_fdb_parent_id`.

### D4 — "Include empty / depleted spools" toggle

Config key `wizard_include_empty_spools` (bool, default `False`) persisted via `get/set_config_value`.
"Empty" is defined as `not archived AND remaining_weight == 0.0` — same predicate as `_compute_empty_active`.

Applied in three places:
1. `wizard_variances` `spool_ids_per_filament`: empty spools omitted from `spool_ids` when toggle=False.
2. `_plan_spoolman_to_fdb` Phase C: `include_empty_spools: bool = True` parameter; when False, skips
   spool plan items for zero-weight spools. The filament/color plan item is still created (toggle only
   controls the *inventory record*, not the color definition).
3. `wizard_preview` / `wizard_execute` both pass the toggle to the planner.

New `GET /wizard/direction` endpoint returns `{import_direction, include_empty_spools}`.
`POST /wizard/direction` extended with `include_empty_spools: bool | None` (optional, backward-compatible).

Frontend Step 2 (`Step2Direction.tsx`): "Include empty / depleted spools" checkbox, default unchecked.
`StepNPreview.tsx` `EmptyActiveEntry` panel: badge turns blue (informational) when toggle=False with copy
"skipped by setting"; amber when toggle=True ("will be imported").

## 2026-06-03 — CI workflows, registry, and main branch protection

### Registry / repo slug

GitHub remote is `crzykidd/filament-bridge`; container registry is
`ghcr.io/crzykidd/filament-bridge`. Image authentication uses `GITHUB_TOKEN` with
`packages: write` permission — no additional secrets needed.

### Migration check command

`alembic env.py` reads the DB path from `settings.data_dir` (env var `DATA_DIR`), NOT from
a `DATABASE_URL` env var. The two required env vars `FILAMENTDB_URL`/`SPOOLMAN_URL` must
also be set for `Settings()` to initialise, even though their values are irrelevant for
schema-only migration checks. Correct CI command:

```
FILAMENTDB_URL=http://localhost SPOOLMAN_URL=http://localhost DATA_DIR=/tmp/alembic-check \
  alembic upgrade head
```

### CI check names (used in branch protection)

Workflow `CI` → jobs named exactly as follows (branch protection contexts =
`CI / <job-name>`):

| Context | Trigger |
|---|---|
| `CI / Lint` | push + PR |
| `CI / Config validation` | push + PR |
| `CI / Migration check` | push + PR |
| `CI / Compose validation` | push + PR |
| `CI / Image build` | PR only |

`CI / Test` (pytest) is a bonus job — NOT a required check.

### main branch protection

Applied via `gh api` (see command below). Required: PR + all 5 checks green, no direct
pushes, no force-pushes. `required_approving_review_count: 0` (single-developer repo).
`strict: false` (branch need not be current with main before merge).

**Verify check names after first CI run.** GitHub registers check contexts only after
they've executed. If the names above don't match what appears in
Settings → Branches → main protection, update them there or re-run the command below.

```bash
gh api -X PUT /repos/crzykidd/filament-bridge/branches/main/protection \
  --input - << 'EOF'
{
  "required_status_checks": {
    "strict": false,
    "contexts": [
      "CI / Lint",
      "CI / Config validation",
      "CI / Migration check",
      "CI / Compose validation",
      "CI / Image build"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

## 2026-06-03 — Wizard: merged Variances step, downstream filtering, master-tare rule

Two coupled problems fixed together:

1. **Downstream steps now filter to the chosen-to-sync set.** An SM filament is *included*
   iff its `wizard_match_decisions` action is `link` or `create`. `skip` and no-decision are
   excluded everywhere: `wizard_weights`, `wizard_variants`, and the new `wizard_variances`
   endpoint. Helper `_included_sm_ids(db)` is the single definition; all three endpoints call
   it. Before this change, the Weights and Variants steps re-fetched and showed the entire
   Spoolman library, forcing users to deal with filaments they had already decided to skip.

2. **Weights + Variants merged into one "Variances" step.** Wizard order is now 6 steps:
   Connectivity → Direction → Matches → **Variances** → Preview → Execute.
   `Step4Weights.tsx` and `Step5Variants.tsx` are deleted; `StepVariances.tsx` replaces them.
   The FDB import direction reuses the old `GET /wizard/variants` and `GET /wizard/weights`
   endpoints directly from within `FDBVariancesStep`; no backend changes for that direction.

3. **Tare is per filament/group, not per spool.** Filament DB stores one `spoolWeight` per
   filament (not per spool). The new `GET /wizard/variances` endpoint returns one tare per
   SM filament (from the filament-level `spool_weight`; default 200 g). The UI shows one
   editable tare input per variant group (the master's) and one per standalone filament. On
   save, the frontend expands these to per-spool `WizardTareOverride[]` entries covering every
   spool of every filament in each group. The execute contract (`WizardExecuteRequest.
   tare_overrides`) is unchanged — tare overrides still ride in the request body.

4. **Master-tare-wins with a visible warning.** All variants in a group share the master's
   tare. A banner on the UI makes this explicit: "All variants in this group will use the
   master's empty-reel tare: N g." This is the only correct model given FDB's single-tare
   per-filament constraint.

5. **Editable variant membership; clusters are hints only.** The user can un-check a member
   to remove it from a group (it becomes standalone with its own tare), or click "+ Add
   member" to pull any other included-but-ungrouped SM filament into the group. The saved
   `SMVariantDecision[]` (in `wizard_sm_variant_decisions`) is authoritative; the API's
   suggested groupings are hints only. Groups reduced to master-only are treated as flat
   (no `SMVariantDecision` entry emitted).

6. **Conflicts recompute live.** `VariancesFilament` carries comparable props
   (material/density/spool_weight/temps). When the user changes the master radio button,
   the frontend recomputes conflicts via `computeConflicts()` — a pure function that
   mirrors `sm_prop_conflicts` from `backend/app/core/matcher.py` — without a round-trip.

7. **Step3Matches row separator fix.** Group-body `divide-gray-50` changed to
   `divide-gray-100` so member row dividers are visible on white backgrounds.

## 2026-06-01 — De-adopted the vexp-context-engine standard (sunset homelab-wide)

vexp is being removed across the homelab; the `vexp-context-engine` standard is deprecated and
rewritten as a removal guide at **v3.0.0**. filament-bridge was its first adopter (fully wired at
v2.1.0); all wiring is stripped here:

- Deleted the `.claude/hooks/vexp-guard.sh` PreToolUse guard hook.
- Removed the `mcp__vexp__*` entries from `permissions.allow` and the `hooks` block from
  `.claude/settings.json`. **The `sandbox` block (repo-sandbox-permissions, repo-wide) and the
  `Read/Edit/Write(**)` allows live in the same file and were preserved intact** — JSON re-validated.
- Removed the "Context search (operational rules)" section from `CLAUDE.md`.
- Dropped the vexp `.gitignore` block; untracked `.vexpignore`, `.vexp/.gitignore`,
  `.vexp/.gitattributes`; deleted the `.vexp/` runtime dir and the gitignored auto-generated
  `.claude/CLAUDE.md`.
- Flipped the `standards.md` vexp row to de-adopted/sunset (v3.0.0 guide) and dropped the vexp
  reference from the `repo-sandbox-permissions` row note.

**Not done from this repo:** host daemon teardown is the Ansible `devworkstation` role's opt-in
`--tags vexp_teardown`. A still-running daemon transiently recreated the (now-untracked) `.vexp/`
runtime dir during this change; it clears when the daemon is stopped by the teardown. No
`CHANGELOG.md` exists yet (pending first release), so this record stands in for the changelog note.

## 2026-06-01 — Match-review v2: one unified table, Group-By Status default

Replaced the four fixed status tables (v1) with a single unified table that has a toolbar for Group By, Sort By + direction, global search, Status filter, and per-column filter inputs (Name, Material). Collapsible groups with tri-state checkboxes and right-aligned aggregates.

1. **Group-By Status is the default**, reproducing the v1 four-section feel (Matched / Ambiguous / Unmatched-SM / Unmatched-FDB) while allowing the user to pivot to Material or Brand grouping. Status also appears as a column and filter.
2. **No backend changes.** All fields needed by the new columns (name, vendor, material, color, confidence, vendorDedup, candidates) were already present on `FilamentRef` / `MatchPairRow` / `AmbiguousRow`. Spool-count aggregates would require fetching spools in `wizard_matches`; omitted as optional per the prompt.
3. **All v1 decision logic preserved unchanged**: tri-state checkboxes, Rescan + decision pruning, `saved_decisions` rehydration, ambiguous candidate picker, `bulkSet` per-status action mapping. `unmatched_fdb` rows remain informational (no checkboxes) regardless of grouping.
4. **Status breakdown pills** appear in group headers when Group-By is Material or Brand, showing counts per status within that group. Amber ⚠ badge flags groups with unresolved ambiguous rows.

## 2026-05-31 — FDB location semantics: locationId (ObjectId reference), pre-creation required

Verified against the live FDB instance while implementing spool location seeding (SM→FDB wizard
execute path).

1. **FDB spools use `locationId`, not a bare `location` string.** `POST /api/filaments/:id/spools`
   with `"location": "name"` silently ignores the key. The correct field is `"locationId"` holding
   a 24-char MongoDB ObjectId referencing the `locations` collection. The bridge schema
   `FDBSpoolDetail.location` was wrong and has been corrected to `locationId`.

2. **Locations must be pre-created via `POST /api/locations`.** FDB does not auto-create a location
   from a name. The wizard seed fetches `GET /api/locations` once per run to build a `name→id`
   cache, then creates missing locations on-demand per spool. A `create_location` failure is
   per-record (that spool fails; the run continues) — consistent with the existing NFR-4
   per-record isolation pattern.

3. **Scope of this change.** Only the SM→FDB initial-seed path (wizard execute). Ongoing-sync
   location updates (engine diff) and the FDB→SM direction are out of scope — follow-up work.

## 2026-05-31 — Match-review redesign: grouped tables, checkboxes, rescan

FR-3/FR-4 match-review step rebuilt from a flat list into four independent grouped/sortable tables.

1. **Status is the top-level grouping — four tables stay separate.** Match status (Matched /
   Ambiguous / Unmatched-SM / Unmatched-FDB) dictates what action is even possible per row,
   so it's the outer split. Subgrouping (Material or Brand/vendor) happens *inside* each table
   via a single shared dimension control.

2. **Checkbox → action mapping (per table).**
   - Matched: checked = `link` (to the auto-matched FDB filament), unchecked = `skip`.
   - Unmatched-SM: checked = `create`, unchecked = `skip`. Both default to the "include" action.
   - Ambiguous: row checkbox only active once a candidate is chosen via the Link picker;
     toggles between the chosen `link` (preserving `filamentdb_id`) and `skip`. The `filamentdb_id`
     is preserved in the decision even when `action="skip"` so re-checking restores the link
     without re-picking.
   - Unmatched-FDB: informational only — groupable/sortable, no checkboxes.
   - Subgroup-header checkbox is tri-state (checked/unchecked/indeterminate); table-level checkbox
     covers all rows in the section.

3. **Rescan keeps choices.** `GET /wizard/matches` now accepts a `db` dependency and returns
   `saved_decisions: list[MatchDecision]` (echoing `wizard_match_decisions` from BridgeConfig).
   On first load the UI hydrates `decisions` state from `saved_decisions`. On rescan
   (`reload()`), existing choices are kept and pruned to the SM ids still present in the new
   response — keyed by `spoolman_filament_id`.

4. **`material` added to `FilamentRef`.** `_sm_ref` sets `material=sm.material` (Spoolman
   `SpoolmanFilament.material`); `_fdb_ref` sets `material=fdb.type` (FDB `FDBFilament.type`).
   Used for the Material subgroup dimension in the UI.

## 2026-05-31 — Wizard preview (FR-4 foundation): reconcile-flag keys + read-only UI step

`GET /api/wizard/preview` reuses the same `_plan_spoolman_to_fdb` planner as
`wizard_execute` (so preview ≡ execute), then derives four reconcile-flag lists from the
plan via pure helpers in `backend/app/api/wizard.py`. The non-obvious grouping keys:

1. **`name_collision`** (`_compute_name_collisions`): key is `normalize_name(payload.name)`
   over the *create* plan items. A group flags `vs_existing` when the normalized name is
   also a key in the existing-FDB map, and `intra_batch` when ≥2 incoming creates share the
   key. One entry per distinct normalized name (not per filament) — so the count is groups,
   while the backlog's "43" counted the colliding *filaments*.
2. **`empty_active`** (`_compute_empty_active`): straight over `sm_spools` —
   `not archived AND (remaining_weight or 0) == 0`. Independent of the plan.
3. **`default_tare`** (`_compute_default_tare`): create spool items where
   `tare_source == "default"` (planner substituted the 200 g default because no
   `spool_weight` was set); reports the planned gross and the default used.
4. **`variant_group`** (`_compute_variant_groups`): key is
   `(normalize_vendor(vendor), _strip_color(name, color_hex), normalize_name(material))`
   over create items, groups of ≥2. Fills FR-6's gap (which only groups *matched* records
   and returns nothing on an empty FDB) for fresh imports. No `parentId` is written — the
   proposed groups are surfaced for the future decision UI only.

**UI:** new read-only `frontend/src/pages/Wizard/StepNPreview.tsx`, wired into the stepper
*before* Execute. Shows the plan summary + flag counts and four collapsible flag sections,
with a non-blocking notice that flagged items need decisions in a later release. No mutating
controls.

**E2E (clean FDB, reseeded `spoolman-livedata.db`, 175 fil / 223 spools):** preview returned
`empty_active=63`, `default_tare=79` (exact backlog match), `name_collision=17` groups /
60 colliding filaments, `variant_group=1`; FDB stayed empty and Spoolman unchanged (no
cross-ref extras written) — confirming the read-only guarantee.

## 2026-05-30 — Dashboard dry-run: SyncPreviewEntry shape and skip coverage

Decisions made while implementing FR-14 per-category detail (created/updated/conflicts/skipped).

1. **Typed `SyncPreviewEntry` Pydantic model** (option b). The WIP wizard-preview changes in
   `schemas/api.py` are purely additive (new model classes at the bottom); `CycleResultResponse`
   was untouched, so adding `SyncPreviewEntry` + changing the one-line `preview` type was safe
   and additive. Frontend gets full TypeScript inference with no extra effort.

2. **Preview entry shape** — all 11 fields present on every entry, with `None` for N/A.
   Consistent shape avoids runtime `?.` chains in the frontend and makes the Pydantic model
   validator simple. `old`/`new` on weight conflicts hold SM `remaining_weight` and FDB
   `totalWeight` respectively (labeled in `reason`).

3. **`sm_skipped_fields` set in `_apply_field_changes`** — introduced to prevent the SM→FDB
   dry-run second-pass from emitting duplicate update entries for inherited-skipped fields.
   Local to the function, dry-run only. The live-sync path is unchanged.

4. **Skip entries for archived and first-baseline paths** were previously silent (incremented
   `result.skipped` but produced no preview entry). Now each emits a `skip` entry with a
   `reason`, so the "Skipped (n)" section in the UI is actually populated.

5. **Label degradation rule** — `_preview_label()` builds "VENDOR NAME COLOR (SM #id) / FDB name"
   when all data is present; degrades gracefully to just FDB name, just SM id, or "unknown" if
   parts are missing (e.g. archived spool where sm_spool object is None).

## 2026-05-30 — Multicolor filament mapping (Spoolman ↔ Filament DB)

Spoolman models multicolor (`multi_color_hexes` CSV + `multi_color_direction` =
`coaxial`/`longitudinal`; 29/175 of the live set). Filament DB has **no multicolor
support** — one `color` hex + a `colorName` string. Note: FDB's UI "Notes" field is
actually `settings.filament_notes` inside the **off-limits slicer-passthrough bag**, so we
never write there. Decisions:

1. **Spoolman is authoritative for color; the bridge's own DB is canonical.** FDB can't hold
   multicolor and has no structured extension field, so nothing is stored in FDB beyond a
   display projection. No data loss — Spoolman + the bridge snapshot retain the full set.
2. **FDB gets primary `color_hex` → `color`, plus a human projection in `colorName`** (a
   real top-level field, never `notes`/`settings`). Format is a config choice
   (`multicolor_colorname_format`): `name` (default — fuzzy nearest-named-color over a
   standard palette, e.g. `"Yellow/Green (coextruded)"`) or `hex`
   (`"cdde1b/68cc16 (coextruded)"`). Type vocabulary is friendly: `coaxial`→**coextruded**,
   `longitudinal`→**gradient**.
3. **`colorName` is a bridge-managed derived field** — recomputed from Spoolman data + the
   current format on each apply for multicolor filaments, so changing the format setting and
   re-running sync rewrites it (the differ won't see a Spoolman-side change). The fuzzy name
   match is approximate by design; switching to `hex` is the escape hatch.
4. **Protect multicolor on write-back.** New setting `protect_multicolor_color_in_spoolman`
   (default **true**): ongoing FDB→Spoolman sync never writes color fields for filaments
   Spoolman marks multicolor, regardless of the material-properties source-of-truth, so
   `multi_color_hexes`/`direction`/`color_hex` can't be flattened. Disabling it carries a UI
   loss-warning.
5. **Forward path:** an upstream feature request was filed for native FDB multicolor. If it
   lands, replace the `colorName` projection with a real field mapping and push correctly —
   no data-model rework, since Spoolman + the bridge already hold the truth.

## 2026-05-31 — Structured multicolor sync supersedes the colorName projection

Filament DB **v1.33.0** (closing [hyiger/filament-db#477](https://github.com/hyiger/filament-db/issues/477))
shipped native structured multicolor, so the "forward path" above has landed. The interim
`colorName`-text projection (decisions 2–4 of the 2026-05-30 entry) is **removed entirely**
— pre-first-release, so no migration. Replacement decisions:

1. **Structured field mapping, both directions.** FDB `color` (nullable) + `secondaryColors[]`
   + arrangement in `optTags` (tag **29 = coextruded**, **28 = gradient**, coextruded wins)
   ↔ Spoolman `color_hex` + `multi_color_hexes` + `multi_color_direction`. Helpers live in
   `core/color.py` (`sm_multicolor_to_fdb`, `fdb_multicolor_to_sm`). coaxial → FDB `color`=null
   & all hexes in `secondaryColors`; longitudinal → `color`=primary, rest secondary. optTag
   writes preserve unrelated tags.
2. **Bidirectional, mirroring the field-diff model.** Multicolor is a filament-level property,
   so `engine._sync_multicolor` runs over filament mappings with a system-agnostic
   `multicolor_signature` stored as filament-level snapshots. One-sided change → directional
   write; both sides changed & disagree → queued conflict (`field_name="multicolor"`), never
   auto-resolved. SoT is not consulted for one-sided changes (consistent with field sync).
   The generic `color` field-map sync is skipped for multicolor filaments (the structured path
   owns it), which replaces the old `protect_multicolor` setting.
3. **Version-gated.** FDB has no version endpoint; we read `GET /api/openapi` → `info.version`
   (`FilamentDBClient.get_version`, cached, refreshed per health probe). `core/version.py`
   gates on `>= 1.33.0` (`MULTICOLOR_MIN_FDB`). On older FDB, multicolor sync is skipped and
   `/api/health` (+ sync status) surface an "upgrade to 1.33.0" warning; single-color `color`
   sync is unaffected.
4. **Removed config** — `multicolor_colorname_format` and `protect_multicolor_color_in_spoolman`
   (defaults, schemas, API, and Settings UI controls) are gone.

## 2026-05-30 — Phase 5 sync fixes (PATCH, weight precision, material default, wizard gating)

Four concrete bugs exposed by the first live end-to-end run (223 Spoolman spools):

1. **`PATCH /api/v1/spool/{id}`, not `PUT`.** Spoolman v0.23.1 returns 405 on `PUT` for
   spool updates; `PATCH` returns 200. This affected both the wizard cross-ref write-back
   and the FR-10 ongoing weight sync (both go through `update_spool`). `CLAUDE.md`
   endpoint list corrected accordingly.

2. **Configurable weight precision (default 2 decimal places).** Without rounding,
   Spoolman's full-precision floats flowed straight through (e.g. `739.4936014320408`).
   `precision` is now a keyword arg on both `spoolman_to_fdb_gross` / `fdb_to_spoolman_net`
   (default 2), threaded from the `weight_precision_decimals` config key (range 0–4).
   Safe from sync churn: the maximum rounding delta at precision 2 is 0.005 g, far below
   the `sync_weight_threshold_grams` default of 2 g.

3. **Missing `material` defaults to `"Unknown"`.** Spoolman allows `material: null`;
   Filament DB requires the `type` field and returns 400 without it. When material is
   absent, the bridge substitutes `"Unknown"`, logs a warning naming the Spoolman filament
   id, and continues. Silent invention was rejected — the warning makes the substitution
   auditable.

4. **`wizard_completed` only flips on zero failures.** Previously the flag was set
   unconditionally after any non-fatal run, so a run with 211 failures still reported
   completion. Now `wizard_completed` is only set `true` when `failed == 0`. Users can
   re-run after fixing issues; idempotency already skips already-linked records so reruns
   are safe.

Architecture / approach decisions for filament-bridge, newest at top. One entry per
non-obvious call: a change of approach, a rejected alternative, or a workaround. Keep
entries short — the *why*, not a tutorial. Part of the
[handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md)
standard (see `standards.md`).

## 2026-05-30 — Make docker-compose deployable + SPA route fallback

Bringing the stack up locally surfaced four problems; all fixed.

1. **Upstream images live on GHCR, not Docker Hub.** `docker-compose.yml` referenced
   `hyiger/filament-db` and `donkie/spoolman` (both nonexistent on Docker Hub →
   `pull access denied`). Correct refs: `ghcr.io/hyiger/filament-db:latest`,
   `ghcr.io/donkie/spoolman:latest`.
2. **Spoolman listens on 8000 internally.** The compose mapped `7912:7912` but Spoolman
   binds 8000 by default, so nothing answered on 7912. Set `SPOOLMAN_PORT: "7912"` so the
   host mapping *and* the in-network `http://spoolman:7912` (used by the bridge service)
   both resolve. The whole project assumes Spoolman on 7912.
3. **Filament DB needs MongoDB.** It's a Next.js app that 500s on every API call without
   `MONGODB_URI`. Added a `mongo:7` service + `MONGODB_URI: mongodb://mongo:27017/filamentdb`,
   and dropped the meaningless `filamentdb-data:/data` volume (its state lives in Mongo).
4. **SPA route fallback.** Phase 4 served the build with `StaticFiles(html=True)`, which
   only serves `index.html` at the root — every client route (`/conflicts`, `/wizard`, …)
   404'd on hard refresh / direct load / shared link, since the app uses `BrowserRouter`.
   Replaced with: mount `/assets` for hashed bundles, plus a catch-all `GET /{full_path:path}`
   that returns the matching file if it exists else `index.html`. Guarded to still 404
   unknown `/api/*` paths (as JSON) rather than swallowing them into the SPA shell. Whole
   block stays behind `if _static_dir.is_dir()`, so pytest / `uvicorn --reload` are
   unaffected (no `/static` dir in dev).

**`docker-compose.dev.yml`** (tracked): same services with data bind-mounted under the
gitignored `./private_data/` instead of named volumes — lets you seed/inspect data from
the host. Safe to track because no real data is ever committed.

**Deep-link base caveat (known, not fixed):** the UI builds deep links from the URLs the
bridge reports (`systems[*].url`), which in compose are docker-internal names
(`http://filament-db:3000`). Browsers can't resolve those, so deep-link icons don't click
through in a localhost-only compose run. In a real LAN deployment the upstream URLs resolve
from both the bridge and the browser, so they work; for local poking, run the bridge in
host dev mode (uvicorn + `backend/.env` → `localhost:3000`/`7912`).

## 2026-05-29 — Phase 4 Web UI: SPA scaffold, static mount, deep-link bases, hooks

Key decisions taken while building the React SPA.

1. **`frontend/dist` → `static/` in the Docker image; mount guarded by `is_dir()`.**
   The Vite build writes to `frontend/dist`; the Dockerfile copies it to `/app/static/`
   in the runtime image. `main.py` resolves `Path(__file__).parent.parent.parent / "static"`
   and only calls `app.mount` when the directory exists — so `pytest` and local
   `uvicorn --reload` (no frontend build) pass without error. `html=True` on
   `StaticFiles` provides the SPA fallback for client-side routes.

2. **Deep-link bases come from `/api/health` `systems[*].url`, not env vars.**
   The backend already returns the configured `FILAMENTDB_URL` / `SPOOLMAN_URL` in the
   health response. `DeepLinkContext` fetches `/health` once on mount and provides the
   bases to all `DeepLinks` components. This means the UI never needs its own copy of the
   env vars and stays correct even if the backend is pointed at non-default URLs.

3. **Plain `fetch` + hooks, no react-query.**
   Two hooks — `useApi` (one-shot, re-runs on dep change) and `usePoll` (interval
   auto-refresh for the dashboard). Avoids a heavy dependency for a simple internal tool;
   adding react-query later is straightforward if the data requirements grow.

4. **Tare overrides are held in WizardShell state, not in a URL or context file.**
   The FR-5 weight-review step collects per-spool tare overrides and passes them into the
   `WizardShell` component's `tareOverrides` state. Step 6 submits them in the execute
   body. This matches the backend contract (the server does not persist tare overrides
   between calls) and keeps the wizard self-contained.

5. **Wizard step navigation is driven by the stepper index + React Router.**
   `WizardShell` owns the current step index and calls `navigate('/wizard/<path>')` on
   `next()`/`prev()`. Steps are plain route components with no shared session storage —
   each re-fetches its data from the API when mounted. This is correct for a wizard that
   is run once; it avoids stale cached state if the user navigates back and re-fetches.

## 2026-05-29 — Phase 3b wizard execute (FR-7): create order, idempotency, snapshot seed, fatal vs per-record

Decisions taken while building `POST /api/wizard/execute` — the initial bulk
write to both upstreams.

1. **Create order = filaments → variants → spools, in three passes.** Phase A
   resolves every source filament to a target filament id (link to an existing
   one, or `create_filament`). Phase B applies the FR-6 variant groupings
   (`update_filament` with `parentId`) as a *second pass* rather than setting
   `parentId` at create time: the variant decisions are keyed by FDB filament id,
   and a just-created filament has no id at decision time — so a variant decision
   can only reference a pre-existing (linked) filament. By the time Phase B runs,
   every referenced filament exists, so "parents before children" is satisfied
   for free. Phase C creates the `FilamentMapping`/`SpoolMapping` rows and seeds
   the spools. The parent id is resolved before spool seeding so the
   `filamentdb_parent_id` cross-ref and the `FilamentMapping.filamentdb_parent_id`
   column are written in one shot.

   **Superseded for the `spoolman` direction (2026-05-31, see below):** the
   FDB-keyed two-pass rationale only ever held because variant decisions were
   keyed by FDB filament id. That breaks in a greenfield FDB (no ids to key on),
   so the `_execute_spoolman_to_fdb` path now keys decisions by *Spoolman*
   filament id and injects `parentId` at create time (Pass 2), not via a
   post-hoc `update_filament`. The two-pass `update_filament(parentId)` approach
   survives only for the `filamentdb` direction (`_execute_fdb_to_spoolman`).

2. **Idempotency is keyed on the bridge's own mapping tables *and* the upstream
   cross-ref field.** Before creating, we skip if a `FilamentMapping`/`SpoolMapping`
   row exists (the normal re-run case) *or* if the Spoolman spool already carries a
   `filamentdb_spool_id` extra value (a prior run wrote upstream but its DB
   transaction rolled back — the commit is at the very end). This makes a re-run
   after a partial failure a no-op rather than a duplicator. Nothing upstream is
   ever deleted to "clean up" a partial run (CLAUDE.md hard rule); the re-run
   reconciles.

3. **Fatal vs per-record failure governs the `wizard_completed` flip.** A failure
   to *read* both systems is fatal — we write an error `SyncLog`, do **not** flip
   `wizard_completed`, and return `502 upstream_fetch_failed` (nothing was
   written). A single record's API error is isolated (NFR-4): it becomes a
   `failed` report entry + an `error` `SyncLog` and the run continues; the flag
   still flips, since the user can re-run to reconcile. There are no conflicts to
   queue here — the wizard is the user explicitly choosing the initial state
   (conflicts are an ongoing-sync concept, FR-13).

4. **Seed weights are SET on create, never logged as usage.** New target spools
   get their converted gross/net weight set directly on `create_spool`. Usage
   entries (`log_usage`) are reserved for ongoing decrements (FR-9); emitting them
   for the seed import would invent a fake consumption history.

5. **Snapshots are seeded post-write (best-effort).** Each freshly-linked pair
   gets both snapshot rows written using the engine's own
   `_sm_snapshot_dict`/`_fdb_snapshot_dict`/`_upsert_snapshot` helpers, so cycle 1
   of auto-sync diffs against a correct baseline instead of treating every record
   as first-seen. A snapshot-write error is swallowed (the engine baselines a
   first-seen pair anyway) so it can never fail the import.

6. **Tare overrides ride in the execute request body, not BridgeConfig.** Unlike
   match/variant decisions, the FR-5 per-spool tare overrides are *not* persisted
   in Phase 3 (there is no `POST /wizard/weights`). The UI collects them on the
   review screen and submits them with the execute call
   (`WizardExecuteRequest.tare_overrides`, keyed by whichever spool id the active
   direction uses). Absent an override, tare falls back to the spool's, then the
   filament's, `spool_weight`, then the 200 g default.

7. **Direction-model asymmetry (documented limitation).** The persisted
   `MatchDecision` is Spoolman-keyed (`link`/`create`/`skip` per Spoolman
   filament). It cleanly drives the `import_direction="spoolman"` path. For
   `import_direction="filamentdb"` the same link decisions still pair both ids,
   but FDB filaments with no link decision are created in Spoolman with no
   per-record skip granularity (the FR-4 "skip this unmatched record" choice for
   an FDB-only filament isn't representable in the Spoolman-keyed model). Accepted
   for now; revisit if the FDB-import direction needs per-record skips.

## 2026-05-29 — Phase 3 API: error envelope, conflict-resolve semantics, wizard state, backup format

Five decisions taken while building the bridge API layer (Phase 3):

1. **Error envelope.** Handled errors return `{"detail": {"code": <machine
   code>, "message": <human message>}}` via a single `api/errors.py:api_error()`
   helper. `code` is a stable string the UI branches on (e.g. `wizard_incomplete`,
   `manual_value_required`, `mapping_not_found`); `message` is for display.
   FastAPI's own validation (Pydantic `Literal`/`gt`) still returns its native
   422 shape — we don't wrap those.

2. **Conflict resolution = record now, apply on a later cycle.** `POST
   /conflicts/{id}/resolve` writes `resolution`/`resolved_value`/`resolved_at`
   on the row and drops it from the open queue, but performs **no upstream
   write** (honours the no-auto-resolve hard rule and keeps sync logic in
   `core/`). `resolved_value` is the chosen side's value (spoolman/filamentdb)
   or the supplied `manual` value. ⚠️ Engine gap: `core/engine` does not yet
   read resolved conflicts to push the chosen value upstream (and currently
   re-queues an unresolved weight conflict every cycle). Wiring the engine to
   consume resolutions is a Phase 2 follow-up — tracked, not done here.

3. **Wizard decision state lives in `BridgeConfig`, not a new table.** The
   wizard's direction (`import_direction`), match decisions
   (`wizard_match_decisions`), and variant groupings (`wizard_variant_decisions`)
   are persisted as JSON values in the existing key→JSON `BridgeConfig` store.
   Chosen over a dedicated `wizard_state` table to avoid an Alembic migration for
   transient setup data; Phase 3b reads these keys to execute (FR-7) and flips
   `wizard_completed`. The source-of-truth choices reuse the existing
   `*_source_of_truth` keys directly.

4. **Backup format.** `GET /backup/export` emits a versioned envelope
   (`schema_version = 1`) containing **bridge state only** — config, filament
   mappings, spool mappings, and *open* conflicts — never a copy of upstream
   data (CLAUDE.md). `POST /backup/import` is idempotent: mappings upsert by
   their unique business key (`spoolman_filament_id` / `spoolman_spool_id`)
   preserving ids so spool→filament FKs survive a clean restore; conflicts insert
   only when no equivalent open conflict exists (natural key: entity_type +
   field_name + the two ids). A mismatched `schema_version` is a 400.

5. **Mapping status enum (the `/mappings` + dashboard contract).** Precedence:
   `conflict` (an open Conflict references the spool) > `unlinked` (spool mapping
   has no parent filament mapping) > `pending` (a side has no snapshot yet) >
   `in_sync` (both snapshots present, no open conflict). Per-side weights and the
   name/vendor/color display fields come from the last **snapshots** (the
   Spoolman-side snapshot carries the filament detail; the FDB spool snapshot is
   trimmed), so the endpoint needs no live upstream fetch.

Test-harness note: the in-memory SQLite fixtures use `StaticPool` (one shared
connection) because FastAPI's `TestClient` runs sync handlers in a worker thread,
which would otherwise see its own empty `:memory:` database. `tests/conftest.py`
also `setdefault`s the required env vars so `cd backend && pytest` is
self-contained.

## 2026-05-29 — Async-job / sync-DB bridging approach (Option A — inline)

`run_sync_cycle` is a single `async def` that `await`s client I/O and calls
synchronous SQLAlchemy code inline — no thread, no second sync httpx client.
SQLite latency is microseconds; the only real bottleneck is the HTTP calls to
Spoolman and Filament DB. The brief loop stall is harmless for a single-container
homelab service. Rejected Option B (offload DB to `asyncio.to_thread` with a sync
httpx client) because it would split stack traces across the event loop and a worker
thread, surface errors a step removed from their cause, and require a parallel sync
`httpx.Client` purely to make the thread viable. Only revisit if a much larger
inventory (≫ 1000 spools) makes a cycle long enough to visibly stall the event loop.

## 2026-05-29 — Spoolman extra-field conflict-key definition (Phase 2)

The conflict `field_name` for a weight disagreement is `"weight"` (not
`"remaining_weight"` or `"totalWeight"`) so the resolution UI can display a
single unified weight conflict rather than two system-specific column names.
Field-mapping conflicts use the FDB dotted path (e.g. `"temperatures.nozzle"`)
as the key, which is the canonical name in the bridge's field-map config.

## 2026-05-28 — Canonical build-phase numbering (closes the skipped Phase 2)

The handoff prompts grew a numbering gap: Phase 0 (backend foundation) and Phase 1
(SQLite persistence) shipped, but the prompts then forward-referenced "Phase 3 (sync
engine)" and "Phase 4 (wizard API)" — there was never a Phase 2. The Phase 0 prompt only
mentioned Phase 2 in passing ("clients ... Phase 2 leans on this"). To keep the sequence
contiguous, the remaining work is renumbered to close the gap. This table is the single
source of truth for build-phase numbers; product-facing phases in `README.md` (guided
sync → dry run → auto-sync) and the migration-guide phases are separate schemes and are
unaffected.

| Build phase | Scope | Status |
|---|---|---|
| Phase 0 | Backend foundation — FastAPI skeleton, health (FR-1), upstream clients | ✅ done |
| Phase 1 | SQLite persistence — models, Alembic, config seed | ✅ done |
| Phase 2 | Continuous sync engine — snapshot/diff/match/apply/conflict/log (FR-8…FR-14) | next |
| Phase 3 | Bridge API layer — wizard read/decision endpoints (FR-1…FR-6) + sync/conflict/mappings/config/backup/log routers | planned |
| Phase 3b | Wizard execute (FR-7) — the initial-sync write to both upstreams; carved out for risk/isolation | planned |
| Phase 4 | Frontend SPA + `/static` mount (FR-15…FR-19) | planned |

The forward-references in the two completed prompts under `prompts/done/` were corrected
to match (sync engine 3→2, wizard 4→3, SPA 5→4).

## 2026-05-28 — Synchronous SQLAlchemy (not async) for the persistence layer

Used `create_engine` / `Session` rather than `create_async_engine` / `AsyncSession`.
SQLite latency is microseconds — the only real bottleneck is the HTTP calls to Spoolman
and Filament DB. Async SQLAlchemy + Alembic autogenerate also requires a sync
compatibility shim that adds complexity for zero practical gain. FastAPI runs sync
`Depends` handlers in a threadpool automatically, so sync DB sessions in route handlers
are safe without any extra wrapper.

## 2026-05-28 — Deep-link routes (corrects PRD NFR-7 / CLAUDE.md)

Verified against the live crzynet instances. The spec's guessed patterns were wrong:
- Filament DB filament: `{FILAMENTDB_URL}/filaments/{id}` — **plural**, not `/filament/{id}`.
- Spoolman spool: `{SPOOLMAN_URL}/spool/show/{id}` and filament `/filament/show/{id}` —
  **no hash routing** (newer Spoolman dropped `/#/`).
- Filament DB has **no standalone spool page** — spools render under the filament page.
  So bridge spool rows link to the parent filament page, not a per-spool URL.

## 2026-05-28 — Filament DB variant inheritance: read detail, strip computed fields

`GET /api/filaments/:id` resolves parent→variant inheritance server-side: the variant
response merges inherited values and names which ones in `_inherited[]` (plus `_parent`,
and `_variants[]` on the parent). The trimmed list view (`GET /api/filaments`) is for
enumeration only. Two rules for the bridge: (1) writing a material prop onto a variant
whose field is in `_inherited[]` overrides inheritance — check `_inherited[]` and
skip/flag instead of blindly writing; (2) strip computed/Mongoose fields before any PUT
(`_inherited`, `_parent`, `_variants`, `hasVariants`, `inherits`, `settings`, `__v`,
`instanceId`, `createdAt`, `updatedAt`, `_deletedAt`). Note `inherits` (a PrusaSlicer
preset name) is unrelated to the `parentId` variant tree — do not conflate.

## 2026-05-28 — Spoolman extra fields: create on startup, JSON-decode values

`GET /api/v1/field/spool` returns `[]` on the live instance — none of the bridge's
cross-ref fields exist. The bridge creates `filamentdb_id`, `filamentdb_parent_id`,
`filamentdb_spool_id` via `POST /api/v1/field/{entity_type}/{key}` on startup (chosen
over requiring manual UI setup — keeps deployment env-var-only). Spoolman stores text
extra-field values JSON-double-quoted (`"\"https://...\""`), so the bridge must
`json.loads()` them on read and `json.dumps()` on write, never use raw.

## 2026-05-28 — Sync engine defaults for the three design open questions

Defaults chosen now, revisitable later: (OQ#1) sync a weight change only when the delta
≥ a configurable threshold (default ~2g) to avoid rounding churn between net/gross
models. (OQ#6) full-snapshot diff each cycle — `GET /api/v1/spool?limit=1000` returns
all 223 spools fast enough; add incremental fetch only if a larger inventory demands it.
Note: `limit=1000` includes archived (active+archived both returned 223), so filter
`archived == false` client-side for the active set. (OQ#7) accept the aggregate weight
delta when multiple printers decrement one spool between cycles; per-printer attribution
is out of scope — documented, not silently dropped.

## 2026-05-28 — Docker base images: node:22-alpine (build) + python:3.12-slim-bookworm (runtime)

Multi-stage Dockerfile uses `node:22-alpine` for the React build stage (throw-away, never
ships) and `python:3.12-slim-bookworm` for the final runtime stage. Slim was chosen over
distroless/Chainguard because the service is still under active development — no shell
means no `exec`-based debugging, which is painful for a homelab sync tool. Revisit
distroless (`gcr.io/distroless/python3-debian12`) once the app is stable.

## 2026-05-31 — Unified dry-run: shared planner, auto-decisions, orphan bucket

**Shared planner location:** `_plan_spoolman_to_fdb`, `_SyncPlan`, `_FilamentPlanItem`,
`_SpoolPlanItem`, and `_fdb_filament_payload_from_sm` were extracted from
`backend/app/api/wizard.py` into `backend/app/core/planner.py`. Both `wizard_execute`
(FR-7) and `plan_dry_run` (FR-14) import from there — the same planner code means
preview ≡ execute by construction.

**Matcher → decisions mapping for the dry-run:**
`match_filaments(unlinked_sm, unlinked_fdb)` is called in `core/dryrun.py::plan_dry_run`
and its results are converted to `decisions_by_sm` before the planner runs:
- `matched` (1:1 confidence) → `{action: "link", filamentdb_id: <fdb.id>}` → planner
  emits `update` (filament_link) preview entries.
- `unmatched_spoolman` → `{action: "create"}` → planner emits `create` entries.
- `ambiguous` (multiple FDB candidates) → NOT auto-picked; emitted directly as
  `conflict` with `candidates: [<fdb_ids>]`. The planner never sees ambiguous SM
  filaments (they're excluded from `decisions_by_sm`).

**Cross-ref orphan bucket:** SM spools that already carry the `filamentdb_spool_id`
extra field but have no `SpoolMapping` row (the "167" from the live dataset) are now
bucketed as `update` with `reason: "re-link from existing cross-ref"`. The engine's
previous silent `continue` at the xref guard is preserved for live sync — only the
dry-run re-classifies them. Confirmed with user 2026-05-31.

**False-conflict removal:** `run_sync_cycle(dry_run=True)` buckets SM spools with no
`FilamentMapping` as `conflict(new_spool)` — this is correct for steady-state but wrong
for the initial-state dry-run. `plan_dry_run` filters those entries out (criterion:
`action==conflict, entity_type==spool, field==new_spool, fdb_filament_id==None`) before
adding the planner's reclassified entries.

## 2026-05-28 — Canonical version file is `backend/app/__init__.py`

For the `release-prep-and-cut` standard, the bare version lives in
`backend/app/__init__.py` (`__version__ = "X.Y.Z"`). Chosen over `pyproject.toml`
(the backend uses `requirements.txt`, not pyproject) and a root `VERSION` file (the
FastAPI app would have to parse it at runtime, whereas `__version__` is a native
import that also feeds the in-app version display). The file doesn't exist yet — it's
created when the backend lands.

## 2026-05-31 — Spoolman→FDB variant grouping: SM-keyed master-promote

The initial-sync wizard can now collapse a set of flat Spoolman filaments
(e.g. "ELEGOO PLA Red/Blue/…") into one FDB parent + variants *before* the
write, for the `import_direction="spoolman"` greenfield flow.

**Master = parent (a real filament, not a synthesized one).** Each SM filament
still maps 1:1 to an FDB filament; grouping only orders master-before-variants
and stamps `parentId` on the non-masters. The master is a normal filament with
its own color and spools. The user picks the master (radio) and prunes members
(checkbox); a group reduced to master-only dissolves to flat creates.

**SM-keyed persistence — new `wizard_sm_variant_decisions` key.** Decisions are
keyed by Spoolman filament id (`{master_spoolman_filament_id,
variant_spoolman_filament_ids[]}`), not FDB id, because a greenfield FDB has no
ids to key on. The legacy FDB-keyed `wizard_variant_decisions` +
`VariantDecision` + `_execute_fdb_to_spoolman` path is untouched; the two keys
coexist, one per direction. This corrects the earlier Phase-B rationale (above),
which documented the FDB-keyed two-pass `update_filament(parentId)` as
intentional — it was a workaround for FDB-keyed decisions and does not apply to
the spoolman direction, which injects `parentId` at create time.

**Clustering strips a color-word lexicon, not just the hex.** `_strip_color`
only removed a hex code, which under-clustered real names like "ELEGOO PLA Red".
Clustering now keys on `(normalize_vendor, normalize_name(material), base_name)`
where `base_name` strips both the hex and a known color-word lexicon
(red/blue/black/white/grey/green/…). Clusters are **hints only** — the GUI is
authoritative. Suggested master heuristic: most spools, tie-break shortest name.
Singletons (cluster of 1) are excluded.

**Shared properties are flagged, never auto-resolved.** `sm_prop_conflicts`
compares material/density/spool_weight/extruder_temp/bed_temp between master and
each member; mismatches surface as inline warnings in the preview
(`variant_plan`). The bridge never auto-picks a value (CLAUDE.md hard rule). A
group whose master has a `skip` match-decision is rejected at save; a variant
whose master failed to resolve at execute time emits a `failed` report entry
(no orphan `parentId`).

**Un-grouping after a successful run is out of scope.** The wizard builds the
tree before the first write only; reorganizing an already-synced parent/variant
tree is a separate, later concern.
