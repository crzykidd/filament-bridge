---
name: 2026-06-23-mobile-updates-phase4
status: pending
created: 2026-06-23
model: sonnet
completed:
result:
---

# Task: Mobile Updates & Labels — Phase 4 (docs / PRD / CHANGELOG)

**Documentation only** — Phases 1–3 (backend, frontend, LabelForge) are merged on `dev` and tested.
This phase writes the user-facing docs for the feature. No code changes. Read
`~/.claude/plans/ancient-beaming-star.md` and the merged code/`docs/decisions.md` (the per-phase
notes) for the authoritative details; **verify exact config-key names and endpoint paths by reading
the merged source** (`backend/app/api/mobile.py`, `backend/app/api/labels.py`,
`backend/app/services/labelforge.py`, `backend/app/api/config.py`, `backend/app/models/config.py`,
`backend/app/main.py` for `/r/...`) — do not guess.

## Feature summary to document
A master setting **`mobile_labels_enabled`** (default off) gates the feature. A printed label (via
**LabelForge**) carries brand/color/number + a QR encoding `{bridge_public_url}/r/{fdbFil}/{fdbSpool}`.
`GET /r/{fil}/{spool}` 302-redirects (target = `mobile_redirect_target`: the bridge scan page now,
Filament DB's filament page later — no reprint). The scan page (and the in-nav "Mobile updates" page
with a spool search) let you enter a **scale weight (gross)** and **change location**, then Save →
writes Filament DB + Spoolman + refreshes both snapshots. Weight save mode = `mobile_weight_default_mode`
(`direct_correction` default | `usage`), overridable per save. Auth mirrors the app. **QR rendering
needs a LabelForge `dev` build (>v0.1.3)** — text fields print on any version; document this caveat.

## What to do

1. **New `docs/mobile-updates.md`** — the whole story: enabling the feature; the scan→update flow
   (what the page shows, the gross-weight + net-preview, the weight-mode toggle, location quick-change);
   the QR `/r/` redirect indirection + why (change target without reprinting); label printing
   (LabelForge template the user creates with `{placeholder}` text + a `{qr_url}` QR element, the
   `labelforge_fields` CSV → which fields the bridge sends, the field catalog: brand/color/color_hex/
   number/material/qr_url, the Print buttons, "Test printer"); the **LabelForge `dev`/QR caveat**;
   the weight-mode semantics; a short Settings reference. Match the voice of existing docs (e.g.
   `docs/backups.md`).

2. **Wire it into the indexes**: `docs/README.md`, the `README.md` docs table, and the `CLAUDE.md`
   Project-structure docs tree.

3. **`docs/configuration.md`** — add the new keys to the appropriate tables (env + runtime settings):
   `mobile_labels_enabled`, `bridge_public_url`, `mobile_redirect_target`, `mobile_weight_default_mode`,
   `labelforge_url`, `labelforge_token`, `labelforge_template`, `labelforge_fields`,
   `labelforge_label_media`. Use the EXACT defaults/semantics from the merged `config.py`/`_DEFAULTS`.

4. **`CLAUDE.md`** — add the same keys to the env-var table AND the runtime-editable settings table
   (mirror the wording style of the `backup_*` rows).

5. **`docs/prd.md`** — add **FR-29: Mobile updates & label printing** under a suitable section
   (it's a P1/P2-style enhancement). Cover: the `/r/` redirect + FDB-id indirection, the scan/in-nav
   update pages, weight (gross→absolute, the mode setting+override), location, LabelForge printing +
   the field-catalog/CSV, the `mobile_labels_enabled` gate, auth-mirrors-app, and the LabelForge-dev
   QR caveat. Match the FR style; reference the endpoints by path.

6. **`CHANGELOG.md`** `## [Unreleased]` — an **Added** entry (user-facing prose) for the feature.

## Conventions
- Honor `code-checkin-and-pr`: worktree off `dev`, **`docs:` prefix** (this is docs-only), no
  `Co-authored-by:`. UNATTENDED — don't ask.
- Don't restate giant tables verbatim across files — `configuration.md`/CLAUDE.md hold the key tables;
  `mobile-updates.md` explains + links.

## When done
1. Frontmatter; `git mv` this prompt to `prompts/done/`.
2. ONE `docs:` commit on the worktree branch (specific paths, never `git add -A`, never push).
   Suggested: `docs: mobile updates & label printing — guide, config, FR-29, changelog (mobile/labels phase 4)`.
3. Final message: commit SHA, file list, and anything you were unsure of (esp. any config key/endpoint
   whose exact name you couldn't confirm from source).
