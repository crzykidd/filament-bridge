---
name: 2026-05-29-phase4-frontend
status: completed
created: 2026-05-29
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-05-29
result: React SPA scaffolded with all pages/wizard steps wired to the live API; build green, 85 backend tests passing
---

# Task: Phase 4 — Web UI (React SPA for the whole P1 block)

Stand up the React/TypeScript frontend the project has never had. The backend API is
complete and green (85 tests); this phase builds the UI that drives it so a user can run
the wizard, watch sync status, resolve conflicts, and browse the audit log in a browser.
This implements **FR-15…FR-19** (dashboard, conflicts, sync log, manual sync, synced
records) plus the **FR-1…FR-7 wizard** screens, all against endpoints that already exist.

The goal for this phase is a working, navigable SPA wired to the live API — something the
user can `npm run dev` and click around. Polish (animations, fancy tables) is secondary to
coverage and correctness of the API contract.

## Before you start

- **Read `docs/prd.md`** — FR-1…FR-7 (wizard steps) and FR-15…FR-19 (UI screens). These
  are the screen specs. Also the "UI deep link pattern" section.
- **Read `CLAUDE.md`** — the `frontend/` structure block (component/page layout to match),
  the "Deep links (UI requirement)" section, and the tech stack (React 18+, Vite, Tailwind,
  React Router). Honor those choices; don't swap the stack.
- **Read `docs/decisions.md`** — the verified deep-link routes (plural `/filaments/`, no FDB
  spool page, Spoolman `/spool/show/` and `/filament/show/`, no hash routing).
- **The bridge↔UI API contract is `backend/app/schemas/api.py`** — every response model is
  there with field-level comments. The route table and deep-link rules are reproduced
  below so you don't have to rediscover them, but `schemas/api.py` is the source of truth
  for field shapes — mirror it exactly in `src/api/types.ts`.
- Use the `vexp` `run_pipeline` MCP tool for backend context, not grep/glob.

## Working tree check

Before editing, run `git status --porcelain`. There is no `frontend/` directory yet, so
this phase is almost entirely new files — but cross-reference `backend/app/main.py` (you'll
edit the static-mount TODO) and the `Dockerfile`. If either is dirty, list and ask. Surface
unrelated dirty files once; don't block. This prompt file is exempt.

## API contract (already built — do NOT change the backend shapes)

All routes are mounted under `/api`. No auth. No CORS configured — **dev uses the Vite
proxy** (below), prod serves the SPA same-origin from `/static`, so CORS is never needed.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/health` | — | `HealthResponse` {status, bridge_version, systems{spoolman,filamentdb}} |
| GET | `/api/sync/status` | — | `SyncStatusResponse` (dashboard payload, FR-15) |
| POST | `/api/sync/trigger` | — | `CycleResultResponse` (manual sync, FR-18) |
| POST | `/api/sync/dry-run` | — | `CycleResultResponse` (FR-14 preview) |
| POST | `/api/sync/auto` | `AutoSyncRequest` {enabled} | `AutoSyncResponse` |
| GET | `/api/conflicts?status=open\|resolved` | — | `ConflictResponse[]` |
| POST | `/api/conflicts/{id}/resolve` | `ConflictResolveRequest` | `ConflictResponse` |
| POST | `/api/conflicts/bulk-resolve` | `BulkResolveRequest` | `BulkResolveResponse` |
| GET | `/api/mappings` | — | `MappingRow[]` (FR-19 synced records) |
| PUT | `/api/mappings/{id}` | `MappingUpdateRequest` | `MappingRow` |
| DELETE | `/api/mappings/{id}` | — | 204 |
| GET | `/api/config` | — | `ConfigResponse` |
| PUT | `/api/config` | `ConfigUpdateRequest` | `ConfigResponse` |
| GET | `/api/sync-log?entity_type=&direction=&action=&limit=&offset=` | — | `SyncLogResponse` {items,total,limit,offset} |
| GET | `/api/backup/export` | — | `BackupExport` (JSON download) |
| POST | `/api/backup/import` | `BackupExport` | `BackupImportResponse` |
| GET | `/api/wizard/connectivity` | — | `WizardConnectivityResponse` (FR-1; `blocked` gates next steps) |
| POST | `/api/wizard/direction` | `WizardDirectionRequest` | `WizardDecisionAck` (FR-2) |
| GET | `/api/wizard/matches` | — | `WizardMatchesResponse` {matched,unmatched_spoolman,unmatched_filamentdb,ambiguous} (FR-3) |
| POST | `/api/wizard/matches` | `WizardMatchesRequest` {decisions[]} | `WizardDecisionAck` (FR-4) |
| GET | `/api/wizard/weights` | — | `WizardWeightsResponse` {direction, rows[]} (FR-5) |
| GET | `/api/wizard/variants` | — | `WizardVariantsResponse` {groups[]} (FR-6) |
| POST | `/api/wizard/variants` | `WizardVariantsRequest` {groups[]} | `WizardDecisionAck` |
| POST | `/api/wizard/execute` | `WizardExecuteRequest` {tare_overrides[]} | `WizardExecuteResponse` (FR-7 report) |

Notes the UI must respect:
- **`SystemStatus.url`** (on health/status/connectivity `systems.spoolman` / `systems.filamentdb`)
  is the base URL for that upstream. **Derive the deep-link bases from it** — do not assume
  the bridge knows them any other way. Fetch once, stash in context.
- **Weight overrides are NOT persisted server-side** — the wizard collects FR-5 tare
  overrides client-side and submits them in the `POST /wizard/execute` body. Match/direction/
  variant decisions ARE persisted by their POST endpoints.
- Conflict `resolution: "manual"` requires a `value`; the resolve endpoints 422 without it.
- `MappingRow.status` is one of `in_sync | pending | conflict | unlinked` → the four
  StatusBadge colors (green / yellow / red / grey).

## Deep-link URL construction (FR-7/NFR-7 — required on every record row)

Build from the `systems[*].url` bases, open in a new tab (`target="_blank" rel="noopener"`):
- Filament DB filament: `{filamentdbUrl}/filaments/{filamentdb_filament_id}` (plural).
  **Spool rows link to the parent filament URL** — FDB has no standalone spool page.
- Spoolman spool: `{spoolmanUrl}/spool/show/{spoolman_spool_id}`
- Spoolman filament: `{spoolmanUrl}/filament/show/{spoolman_filament_id}`
- Render an icon when the id is present; render it disabled/absent when the id is null
  (e.g. an unlinked record has no FDB id yet).

## What to do

### 1. Scaffold `frontend/` (match the CLAUDE.md tree)
Vite + React 18 + TypeScript + Tailwind + React Router v6. Files: `package.json`,
`vite.config.ts`, `tsconfig.json` (+ `tsconfig.node.json`), `tailwind.config.js`,
`postcss.config.js`, `index.html`, `src/main.tsx`, `src/index.css`, `src/App.tsx`.

- `vite.config.ts`: dev server proxy so `/api` → `http://localhost:8090`
  (`server.proxy['/api'] = { target: 'http://localhost:8090', changeOrigin: true }`).
- `build.outDir` should target where the Dockerfile expects the SPA (coordinate with
  step 6 — the backend serves it from `/static`). Suggest building to `frontend/dist` and
  having the Dockerfile copy `dist` → the image's `static/`.
- Add a `frontend/.gitignore` (node_modules, dist) or extend the root one.

### 2. Typed API layer — `src/api/`
- `types.ts` — TypeScript interfaces mirroring **every** model in `backend/app/schemas/api.py`
  (and the health `HealthResponse`/`SystemHealth`). Keep the literal unions
  (`SourceOfTruth`, `SyncDirection`, `MappingStatus`, conflict status, etc.).
- `client.ts` — a thin `fetch` wrapper (base `/api`, JSON, throws typed errors on non-2xx
  using the backend error envelope from `api/errors.py`) plus one function per endpoint above.
- A small data hook (`useApi` for one-shot + `usePoll` for the dashboard's auto-refresh).
  No heavy data lib required; plain fetch + hooks is fine. (react-query is acceptable if you
  prefer, but keep deps lean.)

### 3. Shared components — `src/components/`
- `Layout.tsx` — app shell: sidebar/topbar nav (Dashboard, Synced Records, Conflicts, Sync
  Log, Settings, Wizard) + `<Outlet/>`. Show overall connectivity + bridge version in the
  header (from `/health`).
- `DeepLinks.tsx` — the two-icon link component used on every record row (rules above).
  Make FDB vs Spoolman visually distinct.
- `StatusBadge.tsx` — green/yellow/red/grey for `in_sync|pending|conflict|unlinked` (and a
  sensible mapping for system ok/degraded/error).
- `DeepLinkContext` (or similar) providing `{filamentdbUrl, spoolmanUrl}` from health.

### 4. Pages — `src/pages/` (FR-15..19)
- `Dashboard.tsx` (FR-15): last/next sync, auto-sync state, pending conflicts, the
  in_sync/pending/conflict/unlinked counts, both systems' connectivity + counts. Poll
  `/sync/status`. Include the **manual sync** button (FR-18 → `POST /sync/trigger`, show
  the `CycleResultResponse` inline) and an **auto-sync toggle** (`POST /sync/auto`).
- `SyncedRecords.tsx` (FR-19): table from `/mappings` — name, vendor, color, Spoolman
  weight, FDB weight, StatusBadge, last synced, DeepLinks per row. Sortable/filterable.
- `Conflicts.tsx` (FR-16): list `/conflicts?status=open`, per row show both values + a
  resolve control (pick spoolman / filamentdb / manual-value), DeepLinks. Wire single
  resolve; bulk-resolve is a nice-to-have.
- `SyncLog.tsx` (FR-17): paginated `/sync-log` with entity_type/direction/action filters,
  DeepLinks where ids present.
- `Settings.tsx`: GET/PUT `/config` (the three source-of-truth selectors + weight
  threshold). Surface backup export/import (FR-24/25) here or on its own page — at minimum a
  "Download backup" (GET `/backup/export`) and upload-to-import control.

### 5. Wizard — `src/pages/Wizard/` (FR-1..7), the multi-step flow
Stepper with one screen per FR. Gate progression on `connectivity.blocked` (FR-1). Each
record row uses DeepLinks. Steps:
1. **Connectivity** — `/wizard/connectivity`; show versions + counts; block if `blocked`.
2. **Direction + source-of-truth** — `POST /wizard/direction`.
3. **Match review** — `GET /wizard/matches`; render matched / unmatched(both sides) /
   ambiguous; let the user pick link/create/skip and resolve ambiguous; show the
   `vendor_dedup_hint`; `POST /wizard/matches` with the decisions.
4. **Weight review** — `GET /wizard/weights`; show net↔gross + tare source; allow per-row
   tare override (held client-side for the execute call).
5. **Variants (optional)** — `GET /wizard/variants`; confirm/skip suggested parent groups;
   `POST /wizard/variants`.
6. **Execute** — `POST /wizard/execute` with the collected `tare_overrides`; render the
   `WizardExecuteResponse` report (created/updated/skipped/failed + per-record detail +
   deep links). This is the real bulk write — show a clear confirm before firing.

### 6. Wire the SPA into the backend + Docker
- In `backend/app/main.py`, replace the "Phase 4 TODO: mount /static" block with a real
  `StaticFiles(directory=..., html=True)` mount at `/` **after** the `/api` routers, guarded
  so it doesn't crash when the `static/` dir is absent in dev (the dir only exists in the
  built image). SPA-fallback so client routes deep-link correctly.
- Update the `Dockerfile` so the Node build stage runs `npm ci && npm run build` in
  `frontend/` and copies `frontend/dist` into the runtime image where the mount expects it.
- Confirm `docker-compose.yml` still exposes the single port (8090).

## Conventions to honor

- Match the `frontend/` paths in CLAUDE.md (components/, pages/, api/). TypeScript strict.
- Deep links on **every** record row, opening in new tabs; bases from `systems[*].url`.
- `types.ts` mirrors `schemas/api.py` exactly — if you find a mismatch, the backend wins;
  fix the TS, don't change the API.
- Keep dependencies lean (React, React DOM, React Router; Tailwind/Vite toolchain).
- Don't add auth, don't add CORS (proxy in dev / same-origin in prod).
- Don't touch backend route shapes or the engine. Frontend + the static-mount/Dockerfile
  glue only.

## Verification

- `cd frontend && npm install && npm run build` is green (tsc + vite).
- `npm run dev` with the backend running (`FILAMENTDB_URL`/`SPOOLMAN_URL` set, uvicorn on
  8090) loads the dashboard and navigates all pages without console errors. If no live
  upstreams are available, the dashboard should degrade gracefully (show error connectivity,
  not crash).
- Backend tests still green (`cd backend && pytest`) — the static mount must not break the
  app when `static/` is absent.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure).
3. Record non-obvious decisions in `docs/decisions.md` (e.g. build outDir → static mount
   strategy, the SPA-fallback choice, the deep-link-base-from-health decision, any dep
   choices like react-query vs plain fetch).
4. Propose ONE commit (no `Co-authored-by:`). Suggested message:
   `feat: Phase 4 — Web UI (React SPA: dashboard, wizard, conflicts, log, records)`.
   Files: everything under `frontend/`, `backend/app/main.py`, `Dockerfile`,
   `docs/decisions.md`, the prompt move. Present the file list and ask
   `commit these as "<message>"? (y/n)` before staging. Stage specific paths only; commit
   on `dev`; no push.
