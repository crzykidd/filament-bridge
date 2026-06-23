---
name: 2026-06-23-mobile-updates-phase2
status: pending
created: 2026-06-23
model: sonnet
completed:
result:
---

# Task: Mobile Updates & Labels — Phase 2 (frontend mobile flow)

Implements **Phase 2** of the approved plan at `~/.claude/plans/ancient-beaming-star.md` (read it
in full first). Phase 1 (backend) is already merged on `dev`: the endpoints below exist and pass.
This phase builds the UI; **LabelForge print buttons + the full LabelForge Settings fields are
Phase 3** (do not build them now).

## Phase 1 backend already available (use these)
- `GET /api/mobile/spool/{fil}/{spool}` → `MobileSpoolDetail` (brand, color name+hex, number = SM
  spool id, current gross/net/tare, location, FDB/SM ids, `weight_default_mode`). 404 if unmapped.
- `PATCH /api/mobile/spool/{fil}/{spool}` body `{gross_grams?, location?, weight_mode?}` → returns the
  refreshed `MobileSpoolDetail`. (Check the exact field names in `backend/app/schemas/api.py`
  `MobileSpoolDetail` / `MobileSpoolUpdateRequest`.)
- `GET /api/mobile/locations` → `string[]` for a datalist.
- `GET /api/version` now includes `mobile_labels_enabled: boolean` — use it to gate the nav item.
- `GET /r/{fil}/{spool}` (302) and the config keys exist; every endpoint 403s when the feature is off.
- Config keys already wired into `ConfigResponse`/`ConfigUpdateRequest`: `mobile_labels_enabled`,
  `mobile_redirect_target`, `mobile_weight_default_mode` (+ the `labelforge_*` keys — leave those for Phase 3).

## Before you start
- Read the frontend conventions in `frontend/src/pages/SyncedRecords.tsx`, `Conflicts.tsx`,
  `Login.tsx`, `components/Layout.tsx`, `components/DeepLinks.tsx` + `DeepLinkContext.tsx`,
  `components/ColorDisplay.tsx`, `api/client.ts`, `api/types.ts`, `api/hooks.ts` (`useApi`), and how
  the app reads `/api/version` (the version badge / any version context) so you can read
  `mobile_labels_enabled`.
- Honor `code-checkin-and-pr`: worktree branch off `dev`, `feat:` prefix, no `Co-authored-by:`. You
  run UNATTENDED — do not ask.

## What to do

### 1. Routing (`src/App.tsx`)
- Add `/scan/:filId/:spoolId` as a **sibling route OUTSIDE** the `<Route element={<Layout/>}>` wrapper
  (bare, no side nav) → `ScanTarget`.
- Add `/mobile-updates` **inside** the Layout wrapper → `MobileUpdates`.
- No auth exception — both follow the existing global gate (`App.tsx:82`), per the plan decision.

### 2. Nav (`components/Layout.tsx`)
- Add a `{ to: '/mobile-updates', label: 'Mobile updates' }` entry to `NAV_ITEMS`, rendered **only when
  `mobile_labels_enabled`** (read from the `/api/version` payload the app already loads; thread the flag
  in however the version data is already exposed, e.g. a small context or the existing version fetch).

### 3. Shared component `src/components/MobileSpoolUpdate.tsx`
Takes `{ filId, spoolId }`. Mobile-first, **centered / narrow** card (model the full-screen frame on
`Login.tsx` — `min-h-screen flex items-start justify-center`, max-w ~ `max-w-md`, generous padding).
- Fetch `GET /api/mobile/spool/{fil}/{spool}` (use `useApi`). Loading/error inline (no toast system —
  match `Conflicts.tsx` inline `<p className="text-red-600">` / emerald success banner).
- Show: brand, `ColorDisplay` swatch + color name, **#number**, current weight (gross + net), current
  location, and `DeepLinks` (FDB/SM).
- **Weight input**: a large numeric input labelled clearly as the **scale / total (gross) weight in
  grams** (`inputMode="decimal"`, big touch target). Show a **live computed net preview** (`entered −
  tare`) and the tare. A small **weight-mode toggle** ("Correct weight" = `direct_correction` vs "Log
  as usage" = `usage`) defaulting to `detail.weight_default_mode`, overridable.
- **Location**: an `<input list=...>` with a `<datalist>` populated from `GET /api/mobile/locations`
  (free text allowed). Pre-fill with the current location.
- **Save**: one `PATCH` with `{gross_grams?, location?, weight_mode}` (only send weight if entered,
  only send location if changed). On success show the refreshed values + an inline success banner;
  on error show the message. Disable Save while submitting. Match the submit pattern in
  `Conflicts.tsx` (set submitting → try → catch sets err → finally).

### 4. Pages
- `src/pages/ScanTarget.tsx` — reads `filId`/`spoolId` from the route, renders `<MobileSpoolUpdate/>`
  bare (this is the QR target; no chrome). If the feature is disabled the API 403s — show a simple
  "feature disabled" message rather than crashing.
- `src/pages/MobileUpdates.tsx` — in-nav page: a **spool search box** reusing the `SyncedRecords`
  filter pattern over `getMappings()` (`MappingRow[]` carries `filamentdb_filament_id`,
  `filamentdb_spool_id`, name/vendor/color). Selecting a result renders `<MobileSpoolUpdate
  filId=... spoolId=.../>` below the search (so you can update without a QR scan). Page title + the
  normal `p-8` shell.

### 5. API client + types (`src/api/client.ts`, `src/api/types.ts`)
- `getMobileSpool(fil, spool)`, `updateMobileSpool(fil, spool, body)`, `getMobileLocations()`. Mirror
  the existing `request`/`json` patterns (same-origin, cookie auth). Add the `MobileSpoolDetail` /
  `MobileSpoolUpdateRequest` TS interfaces matching the backend schema. (No `printLabel` yet — Phase 3.)

### 6. Settings (minimal, so the feature is testable now)
In `src/pages/Settings.tsx` add a small **"Mobile updates"** section with: the **Enable** toggle
(`mobile_labels_enabled`), the **redirect target** (`mobile_redirect_target`: bridge | filamentdb),
and the **default weight mode** (`mobile_weight_default_mode`). Wire into the existing config
load/save (isDirty/handleSave) like the other settings. (The LabelForge URL/token/template fields +
print buttons are Phase 3 — leave a clear seam; don't add them.)

## Tests (`frontend`)
- `MobileSpoolUpdate` renders a fetched detail and Save calls PATCH with the right body (mock the
  client like the existing page tests). A net-preview computation test. Route wiring smoke test if
  practical. Extend `Settings.test.tsx` for the new toggle if easy.
- Run: `cd frontend && npx tsc --noEmit && npx vitest run && npm run build`. All must pass.

## When done
1. Update this file's frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: any non-obvious FE choice (e.g. how the enable flag gates the nav). Full
   user-facing docs are Phase 4.
3. ONE `feat:` commit on the worktree branch (stage specific paths, never `git add -A`, never push).
   Suggested: `feat: mobile updates UI — scan page, in-nav page, update component (mobile/labels phase 2)`.
4. Final message: commit SHA, file list, the frontend command + pass/fail counts, and anything
   deferred/uncertain (especially how you read `mobile_labels_enabled` for the nav gate).
