---
name: 2026-06-23-mobile-updates-phase1
status: done
created: 2026-06-23
model: sonnet
completed: 2026-06-23
result: >
  Backend foundation shipped. Extracted core/weight_ops.py (apply_absolute_weight +
  apply_usage_weight) from conflict_apply._apply_weight (no behavior change — #21
  tests green) and core/locations.ensure_fdb_location (wizard refactored to use it).
  Added core/mobile.py (resolve + live assemble), api/mobile.py (GET/PATCH spool,
  GET locations; gross input; both-snapshot refresh) gated by mobile_labels_enabled
  (403 when off), and the /r/{fil}/{spool} 302 redirect in main.py (registered before
  the SPA catch-all; target switches bridge↔filamentdb). Added all config keys incl.
  labelforge_* (env fallback + BridgeConfig _DEFAULTS + ConfigResponse/Update/_config_response);
  exposed mobile_labels_enabled in GET /api/version. Full suite 1243 passed (1221
  baseline + 22 new), ruff clean. Decisions logged. Frontend/LabelForge/docs roll-up
  deferred to later phases as scoped.
---

# Task: Mobile Updates & Labels — Phase 1 (backend foundation)

Implements **Phase 1** of the approved plan at `~/.claude/plans/ancient-beaming-star.md` (read it
in full first for context, decisions, and the architecture diagram). This phase is backend-only:
the shared helpers, the mobile data/update endpoints, the QR redirect, and the config + feature gate.
Frontend (Phase 2), LabelForge printing (Phase 3), and the docs roll-up (Phase 4) are SEPARATE later
prompts — but **add ALL config keys now** (including the `labelforge_*` ones) so config is touched once.

## Feature recap (one screen)
A printed QR encodes `https://{bridge_public_url}/r/{fdbFilamentId}/{fdbSpoolId}`. Scanning it 302s to
the SPA scan page (Phase 2). That page reads a spool's detail and lets the user enter a **scale weight
(gross)** and **change location**, then Save → write to Filament DB + Spoolman, refresh both snapshots.
A master setting `mobile_labels_enabled` (default off) gates the whole feature.

## Decisions (from the plan — implement exactly)
- Spool identity in URLs = **FDB filament id + FDB spool id**.
- Auth = **mirror the app** (protected routers, the normal `_auth_dep`; no special public router).
- Weight save mode = setting `mobile_weight_default_mode` (`direct_correction` default | `usage`),
  overridable per request. Scale input is **GROSS** → FDB `totalWeight = gross`; SM `remaining_weight
  = gross − tare`; `tare = FDB filament.spoolWeight` (default `core/weight.py:DEFAULT_TARE_GRAMS`).
- `mobile_labels_enabled` off → every endpoint here returns **403** (mirror `api/debug.py:_require_debug_mode`).

## Before you start
- Read `~/.claude/plans/ancient-beaming-star.md`, `CLAUDE.md` (weight-model + anti-ping-pong + auth +
  the `backup_*` config pattern), and `standards.md`.
- Honor `code-checkin-and-pr`: worktree branch off `dev`, `feat:` prefix, no `Co-authored-by:`, docs
  with code. You run UNATTENDED — do not ask for confirmation.

## What to do

### 1. Shared helpers (extract — reuse, don't duplicate)
- **`backend/app/core/weight_ops.py`** — extract the absolute-write + dual-snapshot-refresh core from
  `core/conflict_apply.py:_apply_weight` (693-746) into e.g.
  `apply_absolute_weight(db, spoolman, filamentdb, *, sm_spool_id, fdb_fil_id, fdb_spool_id, net_w, tare, source)`:
  PATCH SM `remaining_weight = net_w`, PUT FDB `totalWeight = net_w + tare`, `_merge_snapshot` both,
  `_log`. Have `_apply_weight` call it (NO behavior change — the #21 tests in
  `tests/test_cross_system_resolve.py` + `tests/test_api.py` MUST stay green).
  Also add `apply_usage_weight(...)` for the `usage` mode: on a **decrease** (new gross < current FDB
  totalWeight) call `filamentdb.log_usage(fil, spool, delta, source=...)` + set SM remaining + refresh
  both snapshots; on an **increase** fall back to the absolute path. (`log_usage` exists on the FDB client.)
- **`backend/app/core/locations.py`** — `ensure_fdb_location(filamentdb, name, cache=None) -> location_id`,
  extracted from the wizard-inlined block (`api/wizard.py:1756-1834`). Optionally refactor the wizard to
  call it (keep wizard tests green); at minimum the helper exists and is unit-tested.
- **Spool resolve + assemble** (put in `mobile.py` or a small `core/mobile.py`): resolve a
  `SpoolMapping` by `filamentdb_spool_id`; **live-fetch** `spoolman.get_spool(sm_id)` +
  `filamentdb.get_filament(fil_id)` (pick the spool subdoc by `_id`); return a detail payload:
  brand (vendor name), color name + hex, `number` = Spoolman spool id, current `gross` (FDB totalWeight)
  + `net` (SM remaining) + `tare`, `location`, the FDB/SM ids for deep links, and the effective
  `weight_default_mode`. 404 if no mapping.

### 2. Router `backend/app/api/mobile.py` (PROTECTED — included with `_auth_dep` like the others)
Guard EVERY route with a `_require_labels_enabled(db)` dependency (→ 403 when `mobile_labels_enabled`
is off; copy `api/debug.py:_require_debug_mode`'s shape).
- `GET /api/mobile/spool/{fil}/{spool}` → the assembled detail above.
- `PATCH /api/mobile/spool/{fil}/{spool}` — body `{gross_grams?: float, location?: str,
  weight_mode?: "direct_correction"|"usage"}`. Resolve effective mode (body → else
  `mobile_weight_default_mode`). If `gross_grams` given: compute `net = gross − tare`, apply via
  `weight_ops` per mode. If `location` given: `ensure_fdb_location` → `filamentdb.update_spool(fil,
  spool, {"locationId": id})` + `spoolman.update_spool(sm_id, {"location": name})` + refresh both
  snapshots' location. Return the refreshed detail. Validate `gross_grams >= 0` with the error envelope.
- `GET /api/mobile/locations` → sorted distinct location names (FDB `get_locations` names + SM spool
  locations) for the Phase-2 datalist.

### 3. Redirect (`/r/...`) — new RedirectResponse pattern
In `app/main.py`, register a top-level `GET /r/{fil}/{spool}` **before** the SPA catch-all
(`main.py:335`), gated by `mobile_labels_enabled` (403 when off). Return
`fastapi.responses.RedirectResponse(url, status_code=302)` where `url` = `mobile_redirect_target`:
`bridge` → `/scan/{fil}/{spool}`; `filamentdb` → `{FILAMENTDB_URL}/filaments/{fil}`.

### 4. Config (env `app/config.py` + BridgeConfig `_DEFAULTS` + `api/config.py` + schemas — `backup_*` pattern)
Add ALL of these (runtime-editable; env start-up fallback): `mobile_labels_enabled` (bool, default
false), `bridge_public_url` (str, default ""), `mobile_redirect_target` (`bridge`|`filamentdb`,
default `bridge`), `mobile_weight_default_mode` (`direct_correction`|`usage`, default
`direct_correction`), `labelforge_url` (str), `labelforge_token` (str, secret), `labelforge_template`
(str), `labelforge_fields` (str CSV, e.g. `brand,color,number,qr_url`), `labelforge_label_media`
(str, optional). Surface in `ConfigResponse`/`ConfigUpdateRequest`/`_config_response`. Reject invalid
enum values with the error envelope. **Expose `mobile_labels_enabled` to the SPA** — add it to the
`GET /api/version` response (it is public and the app already loads it) so Phase 2 can hide the nav item.

### 5. Tests (`backend/tests/`)
- `weight_ops`: the extraction preserves #21 behavior (run those suites) + a gross-input mobile case
  for BOTH modes (direct_correction sets both sides; usage logs an FDB usage on a decrease).
- `ensure_fdb_location`: found vs created.
- resolve+assemble: by FDB ids → correct payload; 404 on no mapping.
- `mobile.py` endpoints incl. the **403 when `mobile_labels_enabled` off** gate, and PATCH applying
  weight + location with snapshot refresh (assert no re-queue feel: snapshots updated).
- redirect: target switching (`bridge` vs `filamentdb`) + 403 when disabled.
- Run the FULL suite (baseline **1221** passing) + `ruff check .`.

## When done
1. Update this file's frontmatter (`status`, `completed: 2026-06-23`, `result`); `git mv` to `prompts/done/`.
2. `docs/decisions.md`: the weight-core + location helper extractions, the `/r/` redirect indirection,
   auth-mirrors-app, weight-mode setting+override, scale=gross. (Full user-facing docs are Phase 4.)
3. ONE `feat:` commit on the worktree branch (stage specific paths, never `git add -A`, never push).
   Suggested: `feat: mobile updates backend — spool detail/update, QR redirect, config (mobile/labels phase 1)`.
4. Final message: commit SHA, file list, test command + pass/fail counts, and anything deferred/uncertain.
