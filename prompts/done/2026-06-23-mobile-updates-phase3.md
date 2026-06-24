---
name: 2026-06-23-mobile-updates-phase3
status: done
created: 2026-06-23
model: sonnet
completed: 2026-06-23
result: >
  Shipped LabelForge label printing. Backend: services/labelforge.py (per-request
  Bearer client, structured LabelForgeError), api/labels.py (POST /labels/print +
  GET /labels/printer-status, gated by _require_labels_enabled, field catalog +
  CSV selection, qr_url from bridge_public_url or request-derived, registered in
  main.py). Config accessors added; schemas extended (LabelPrintRequest). Frontend:
  printLabel/getPrinterStatus client+types, shared PrintLabelButton (MobileSpoolUpdate
  + SyncedRecords row action gated on mobile_labels_enabled), Settings "Mobile &
  Labels" section with the LabelForge fields + Test printer. Tests: 20 backend
  (test_labels.py) + 6 frontend (PrintLabelButton + Settings). Backend 1263 pass,
  ruff clean; frontend tsc clean, 124 vitest pass, build OK. decisions.md note added.
---

# Task: Mobile Updates & Labels — Phase 3 (LabelForge printing)

Implements **Phase 3** of the approved plan at `~/.claude/plans/ancient-beaming-star.md` (read it
in full first). Phases 1 (backend) + 2 (frontend) are merged on `dev`. This phase adds **label
printing via LabelForge**: a service client, a print endpoint, the Print-label buttons, and the
LabelForge connection fields in Settings. Phase 4 (user-facing docs/PRD roll-up) is separate.

## LabelForge API (verified — code against this stable surface)
- `POST /api/print/{name}` — body `{"fields": {<placeholder>: <string>, ...}, "label_media": null}`.
  Returns `{job_id, status, template, label_media, overflow, preview_url}`. 400 (missing field),
  404 (template not found), 409 (media mismatch — `?override=true` to force).
- `GET /api/printer/status` — `{ready, model, loaded_media:{...}, errors, source}` (unauthenticated).
- **Auth:** single shared Bearer token — send `Authorization: Bearer <labelforge_token>` on every call.
- The named **template is created by the USER in LabelForge** with `{placeholder}` text + a QR element
  whose payload is `{qr_url}`; the bridge only supplies the `fields` values. **CAVEAT:** QR *rendering*
  only exists in LabelForge `dev` (>v0.1.3) — the API is identical, so code against it; document that a
  QR label needs a LabelForge build with that work (the user will deploy it). Don't block on it.

## Config (keys already exist from Phase 1 — just USE + surface them)
`labelforge_url`, `labelforge_token` (secret), `labelforge_template`, `labelforge_fields` (CSV like
`brand,color,number,qr_url`), `labelforge_label_media` (optional), `bridge_public_url`. All are already
in `app/config.py` / `models/config.py:_DEFAULTS` / `ConfigResponse` / `ConfigUpdateRequest` /
`_config_response`. The feature gate `mobile_labels_enabled` + `_require_labels_enabled` also exist.

## Before you start
- Read `app/services/spoolman.py` + `filamentdb.py` (httpx client style), `app/services/` patterns,
  `app/api/mobile.py` (the `_require_labels_enabled` gate + `core/mobile.py:resolve_spool_mapping` /
  `assemble_spool_detail` to reuse for the field data), `app/api/backup.py` (an existing
  proxy-to-another-service pattern), and `app/main.py` (router include + how `app.state` clients are
  built). Frontend: `pages/Settings.tsx` (the "Mobile updates" section to extend), `pages/SyncedRecords.tsx`
  (row actions), `components/MobileSpoolUpdate.tsx`, `api/client.ts`/`types.ts`.
- Honor `code-checkin-and-pr`: worktree off `dev`, `feat:` prefix, no `Co-authored-by:`. UNATTENDED — don't ask.

## What to do

### 1. `backend/app/services/labelforge.py` — httpx client
- Construct from `labelforge_url` + `labelforge_token`; `Authorization: Bearer <token>` header.
- `async print_template(name, fields: dict[str,str], label_media: str | None = None, override: bool = False) -> dict`
  → `POST /api/print/{name}` (add `?override=true` when set). Return the JSON.
- `async printer_status() -> dict` → `GET /api/printer/status`.
- **Graceful errors** — never raise a bare 500; on httpx errors raise/return a structured result the
  endpoint maps to a clear message (mirror `api/backup.py`'s try/except style; surface LabelForge's
  `detail` on 4xx). Build the client per-request from current config (config is runtime-editable), or
  cache+rebuild on change — simplest is per-request given low volume.

### 2. `backend/app/api/labels.py` — protected, gated by `_require_labels_enabled`
- `POST /api/labels/print` — body `{fil: str, spool: str, override?: bool}`. Steps:
  1. Resolve the spool (reuse `core/mobile.resolve_spool_mapping` + a live fetch / `assemble_spool_detail`).
  2. Build the **bridge field catalog**: `brand` (vendor name), `color` (color name), `color_hex`,
     `number` (= Spoolman spool id), `material`, and `qr_url` = the absolute redirect URL
     `{base}/r/{fil}/{spool}` where `base` = `bridge_public_url` if set, else derive from the request
     (`request.base_url` / X-Forwarded-* — strip trailing slash). All values stringified.
  3. Select ONLY the keys named in the `labelforge_fields` CSV (trim/split; ignore unknown names but
     log them). If a listed field isn't in the catalog, skip + warn (don't fail the whole print).
  4. Call `labelforge.print_template(labelforge_template, selected_fields, labelforge_label_media, override)`.
  5. Return the LabelForge job result (or a clear error envelope on failure; 409 media-mismatch should
     surface a message the UI can show with an "override" retry hint).
  - Validate `labelforge_url`/`labelforge_template` are configured (else a clear 400 "LabelForge not configured").
- `GET /api/labels/printer-status` — proxy `labelforge.printer_status()` (for a pre-print check / Settings "test").
- Register the router in `main.py` with the normal `_auth_dep`.

### 3. Frontend
- `api/client.ts` + `types.ts`: `printLabel(fil, spool, override?)`, `getPrinterStatus()`, with the
  response types. Same-origin/cookie pattern.
- **Print label button** on `components/MobileSpoolUpdate.tsx` (below Save) and as a **row action on
  `pages/SyncedRecords.tsx`** (spool rows). Inline success ("Printed — job #N") / error (show the
  LabelForge detail; on a 409 media-mismatch offer a "Print anyway" that retries with `override`).
  Only show the button when `mobile_labels_enabled` (the flag the nav already reads).
- **Settings** (`pages/Settings.tsx`): extend the existing "Mobile updates" section (rename heading to
  **"Mobile & Labels"**) with: `bridge_public_url`, `labelforge_url`, `labelforge_token` (password
  input — mirror how `api_token` is handled), `labelforge_template`, `labelforge_fields` (CSV),
  `labelforge_label_media`. Add a **"Test printer"** button calling `getPrinterStatus()` that shows
  ready/model/loaded media or the error. Fold into the existing isDirty/handleSave flow; grey the
  LabelForge fields when the feature is disabled.

## Tests
- Backend: LabelForge client (mock httpx — print success, 4xx surfaces detail, network error handled);
  `labels.py` — field-catalog built correctly, **CSV selection** (only listed fields sent), `qr_url`
  from `bridge_public_url` vs request-derived, the 403 gate when disabled, "not configured" 400.
- Frontend: Print button calls `printLabel` with the right args + renders success/error; Settings new
  fields render + save. Run `cd backend && .venv/bin/python -m pytest -q` (baseline **1243**) + `ruff
  check .`, and `cd frontend && npx tsc --noEmit && npx vitest run && npm run build` (baseline **118**).
  (Worktree has no node_modules — symlink the main repo's, run, remove before commit; say so.)

## When done
1. Frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md`: the LabelForge field-catalog/CSV mapping + the QR-needs-LabelForge-dev caveat.
3. ONE `feat:` commit on the worktree branch (specific paths, never `git add -A`, never push).
   Suggested: `feat: LabelForge label printing — service client, print endpoint, Settings + buttons (mobile/labels phase 3)`.
4. Final message: commit SHA, file list, both test commands + pass/fail counts, and anything deferred/uncertain.
