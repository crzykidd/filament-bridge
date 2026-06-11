# Docs audit gap report — 2026-06-11

Phase 1 output of `prompts/2026-06-10-release-prep-docs-overhaul.md`. Produced from a full
read of the backend (`backend/app/**`), frontend (`frontend/src/**`), every doc in `docs/`,
README, CLAUDE.md, CHANGELOG, Dockerfile/compose, and the prompt queue. Drives the Phase 2
rewrite (done in the same session, uncommitted).

## 1. PRD (`docs/prd.md`) — FR-by-FR status

| FR | Status | Notes |
|---|---|---|
| FR-1 connectivity | implemented-as-described | |
| FR-2 direction | implemented-as-described | PRD correctly says wizard captures import direction only |
| FR-3 auto-matching | implemented-but-extended | xref pre-match pass (filamentdb_id extra → confidence 1.0) not described |
| FR-4 match review | implemented-but-changed | UI is a single grouped/sortable/filterable table with tri-state bulk include, per-column filters, Rescan, OPT badge/filter, `master_fdb` status; PRD describes three lists |
| FR-5 weight review | implemented-but-moved | Folded into the Variances step (one tare per group / per standalone); standalone weights step only used in FDB→SM direction |
| FR-6 variant grouping | **stale** | Implemented as the Variances step: cluster key (vendor, material, finish), pre-flagged excludes, manual grouping/move/ignore, attach-to-existing-FDB-parent (D3), per-group reconcile of conflicting props, `variant_parent_mode` gate (promote_color vs generic_container) — none of this is in the PRD |
| FR-7 execute | implemented-but-extended | Missing: per-record labels, resilient per-record 409 handling, vendor+material+color naming rule, generic-container pre-pass, container-name rename/skip overrides, stale-mapping recreate, location find-or-create, provenance dates, finish-tag write-back, OpenTag identity merge |
| FR-8 sync cycle | implemented-as-described | two-axis model described correctly |
| FR-9 weight SM→FDB | implemented-as-described | |
| FR-10 weight FDB→SM | **stale formula** | PRD says `totalWeight - spoolWeight - sum(usageHistory.grams)`; the usageHistory subtraction was REMOVED (2026-06-10 decision; it double-counted). Code is `totalWeight - tare` only |
| FR-11 field mapping | implemented-but-extended | Phase A scalars described; the dedicated bed/nozzle temperature pass (`_sync_material_props`) is missing; Phase B status note ("pending Phase B") is stale — Phase B shipped |
| FR-12 new records | implemented-as-described | direction gate (`new_spool_sync_direction`) correct |
| FR-13 conflicts | **stale** | Now three classes (cross_system, deletion, master_divergence). Deletion conflicts only fire when a live, still-linked counterpart exists; otherwise the engine **purges the stale mapping** (2026-06-10). Neither is in FR-13 |
| FR-14 dry run | implemented-as-described | |
| FR-15 dashboard | implemented-but-extended | `sync_blocked` banner, matched-entry preview sections not described (minor) |
| FR-16 conflict UI | **stale** | "resolution … does NOT write upstream … Phase-2 follow-up" — Phase B shipped: master_divergence resolution writes upstream (apply_all / variant_override / ignore) with divergence-context endpoint |
| FR-17 sync log | **stale** | PRD says time-window selector "last 24 h / 7 d / 30 d / all"; implemented as **cycle windows** (last 10 / 25 sync cycles / all) |
| FR-18 manual trigger | implemented-as-described | |
| FR-19 synced records | implemented-but-extended | expandable per-field detail grid, conflict deep-link ("See conflict"), multicolor swatch, hide-empty — partially described |
| FR-20 Discord | not implemented (correctly marked) | |
| FR-21 archive sync | partial (correctly marked) | |
| FR-22 print history | not implemented (correctly marked) | |
| FR-23 bulk ops | partial | bulk conflict resolve ✓; bulk variants/tares exist in wizard, not as standalone tools |
| FR-23b OpenTag | implemented-as-described | color-keywords map + family gate could be added |
| FR-23c debug tools | **stale** | says "two debug endpoints"; there are three (`full-reset` added 2026-06-10) |
| FR-24 backup | implemented-as-described | but see bugs §3 (export omits `is_synthetic_parent`/`conflict_type`, includes auth secrets) |
| FR-25 | folded (correct) | |

**Features that exist but have NO FR / mention in the PRD:**
single-account auth + API token (docs/security.md exists), version display + GitHub update
check, light/dark/system theme, required-settings gate, version hard-gating (mentioned only
in passing), container-parent marker config, Variances reconcile write-back, OpenTag color
keywords / vendor aliases settings, stale-mapping purge + planner stale-recreate.

**Architecture section drift:** per-cycle pass table lacks the temperature pass and the
native-scalar pass; the container-structure tree is missing `conflict_apply.py`, `matcher.py`,
`weight.py`, `dates.py`, `compat.py`, `api/auth.py`, `api/debug.py`, `api/version.py`,
`schemas/`.

## 2. README

- **No mention of bridge authentication at all** — first-visit password setup, login, API
  token, `AUTH_ENABLED` recovery. The "no API keys or tokens are needed" line (about
  upstreams) reads wrong now that the bridge itself has auth. Biggest gap.
- Wizard step list (7 steps with separate "Variant grouping" + "Variances") doesn't match the
  actual 6-step flow (Connectivity → Direction → Matches → Variances → Preview → Execute).
- Env-var table missing: `PUID`/`PGID` (only in prose), `CONTAINER_PARENT_MARKER`,
  `OPENTAG_COLOR_KEYWORDS`, `AUTH_ENABLED`, `BRIDGE_CHANNEL`, `BRIDGE_COMMIT`.
- `SPOOLMAN_FIELD_FILAMENTDB_MATERIAL_TAGS` described as "CSV of ints" / CLAUDE.md says
  "JSON list of ints" — actual wire format is a CSV string (JSON-quoted), see bug B2.
- Debug-mode bullet lists two reset tools; there are three.
- Uncommitted prerequisites edit (enforced minimums, 1.37.0 latest tested) folded into rewrite.
- No mention of: version badge/update check, theme, variant parent mode (a required setting!),
  master-divergence conflicts, native shared-field sync, Synced Records expandable detail.

## 3. Other docs

- **docs/configuration.md** — conflict-policy axis lists only `manual`/`newest_wins`
  (missing `spoolman_wins`/`filamentdb_wins`); env table missing `AUTH_ENABLED`,
  `CONTAINER_PARENT_MARKER`, `OPENTAG_COLOR_KEYWORDS`, `BRIDGE_CHANNEL/COMMIT`;
  runtime-settings table missing `variant_parent_mode`, `container_parent_marker`,
  `opentag_color_keywords`, `api_token`/`api_token_enabled`; debug row says two endpoints.
- **docs/spoolman-writes.md** — `filamentdb_material_tags` example says JSON list `[17]`
  (engine writes CSV `"17"`); missing the master-divergence conflict-apply writes
  (SM filament native fields on apply_all) and wizard parentId/optTags container patches.
- **CLAUDE.md** — material-tags field description stale (JSON list); project tree missing
  `conflict_apply.py`, `dates.py`, `compat.py`, `matcher.py`/`weight.py` are present… missing
  `schemas/`, `api/auth.py`; docs/ tree lists only 4 of 10 files.
- **core/version.py header comment** — says minimums "do NOT hard-block"; they do now.
- **Settings UI "Read the details" link** → `/docs/variant-parent-mode` is a dead link
  (SPA fallback redirects to Dashboard; docs aren't shipped in the image).
- docs/wizard-redesign.md + docs/reconcile-backlog.md are historical and correctly marked.

## 4. Bugs found during the audit (Sonnet fix prompts written)

- **B1 — FR-11 `_field_values` never persisted.** Engine never stores FDB-side mapped-field
  values in the spool snapshot (`_fdb_snapshot_dict` is always called without
  `filament_detail`/`field_maps`), so the differ reads `fdb_then = None` every cycle → any
  mapped field with a non-None FDB value is "changed" every cycle → repeated identical
  FDB→SM writes + log spam (default direction) or spurious conflicts (two_way). Affects
  installs with `FIELD_MAPPINGS`/auto-matched extras.
- **B2 — finish-tag wire-format mismatch.** `api/wizard.py` Pass 2.6 writes
  `encode_extra_value(finish_ids)` → JSON array `"[17]"`, which `core/material_tags.py`
  documents as a Spoolman 400; the engine writes CSV via `serialize_material_tags`. Docs also
  disagree with each other.
- **B3 — `ensure_extra_fields` ignores configured spool-field names.** `_REQUIRED_SPOOL_FIELDS`
  hard-codes the default keys; custom `SPOOLMAN_FIELD_FILAMENTDB_*` values are never created
  (filament-level fields do respect config).
- **B4 — backup export/import gaps.** Export omits `is_synthetic_parent` (FilamentMapping)
  and `conflict_type` (Conflict) → restore breaks generic-container ownership and
  master-divergence typing. Export also includes `auth_secret`, `admin_password_hash`,
  `api_token` (decision needed — see §5).
- **B5 — Dashboard `next_sync_at` uses the env interval**, not the runtime-effective interval.
- **B6 — `/docs/variant-parent-mode` dead link** in Settings.
- **B7 — Spoolman pagination hard cap.** `get_spools`/`get_filaments` fetch `limit=1000` once;
  >1000 records are silently truncated.
- **B8 — custom spool-ID field gaps.** Engine new-FDB-spool orphan guard only works when
  `FILAMENTDB_SPOOLMAN_ID_FIELD == "label"`.
- Minor: Settings copy says "Minimum 30 seconds (0.5 min)" but the UI minimum is 1 minute;
  `/api/version` GitHub fetch is blocking urllib inside an async handler; stale comment in
  `core/version.py`; dashboard dry-run planner ignores `never_import_empties` and variant
  keywords so its counts can differ from wizard preview.

## 5. Decisions surfaced to the user

1. **Backup export contains auth secrets** (`auth_secret`, `admin_password_hash`,
   `api_token`). Recommend excluding all three from `GET /backup/export` (restore keeps the
   live install's auth). Needs sign-off — it changes restore semantics.
2. **Docs serving.** Settings deep-links to `/docs/...` which isn't served. Options:
   (a) link to GitHub blob URLs (cheap, works today — chosen for the doc rewrite),
   (b) ship `docs/` into the image and serve at `/docs/*` (nicer; feature prompt).
3. **Material-tags wire format** — standardize on CSV (engine + OpenTag already do); the fix
   prompt makes the wizard match. Flag if you prefer JSON-list instead.
4. **PRD scope** — new FRs added for auth (FR-26), version/update check (FR-27), and UI shell
   features folded into existing FRs, keeping the PRD a spec rather than a changelog.
