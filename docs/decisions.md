# Decision record

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
