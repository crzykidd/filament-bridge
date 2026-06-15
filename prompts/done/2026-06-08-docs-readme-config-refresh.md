---
name: 2026-06-08-docs-readme-config-refresh
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-08
result: Renamed wizard throughout README; added all missing shipped features; updated configuration.md runtime-editable table.
---

# Task: Refresh README.md + docs/configuration.md for post-overhaul features

Documentation-only. Touch ONLY `README.md` and `docs/configuration.md` (+ prompt move). ONE
`docs:` commit. A parallel agent edits CLAUDE.md/prd and CHANGELOG/decisions — do NOT touch those.
Verify everything against the code.

## A. README.md

1. **Wizard rename**: replace "initial-sync wizard" / "Guided initial-sync wizard" / "First run
   — the wizard" with **"Bulk Import Wizard"** (it's re-runnable, not just initial). Affected
   spots include the feature list (~line 11), the "What it does" / sync section (~76), the
   architecture diagram label (~113), and the first-run section (~199). Note it can be run any
   time to import new filaments.
2. **Add the missing shipped features** to the feature list / relevant sections:
   - **Scheduler & Logs** — runtime-editable sync interval (no restart) + sync-log retention;
     Sync Log page has window views (last N cycles) + clear-log.
   - **Bulk Import Wizard** re-runnable + **"Never import empties"** setting (skips creating FDB
     spool records for depleted spools; the filament definition is still imported).
   - **Pre-write backup safeguard** — describe that the backup dialog *gates* the three write
     actions (Wizard Execute, OpenTag Apply, Enable auto-sync), not just that the buttons exist.
   - **Debug mode** — a Settings toggle (off by default) revealing a Danger Zone with reset
     tools (clear Spoolman FDB cross-refs; reset bridge local state); endpoints are 403-gated.
   - **Conflicts** collapsible/sortable rows; **Synced Records** hide-empty + conflict links;
     **browser-local timestamps**.
3. Leave the **Permissions** (entrypoint/non-root/PUID-PGID), **Quick start** (compose split),
   and **Backups** (FDB `/api/snapshot`) sections AS-IS — the audit confirmed they're correct.

## B. docs/configuration.md

Add to the **"Runtime-editable settings"** table (these are BridgeConfig keys, not env vars):
- `debug_mode` (bool, default false) — exposes the `/api/debug/*` reset tools; off by default,
  do not enable in production.
- `never_import_empties` (bool, default false) — wizard skips creating FDB spool records for
  depleted (0 net weight) spools; filament definition still imported.
- `sync_log_retention_days` (int, default 30; 0 = keep forever) — sync-log row retention.
- `sync_interval_seconds` is now **runtime-editable** in Settings → Scheduler & Logs (the env
  `SYNC_INTERVAL_SECONDS` is the default/fallback) — note this where the interval is documented.

The Permissions/PUID-PGID section in configuration.md is already correct — leave it.

## Verification

- No code touched. `git diff --stat` shows only README.md + docs/configuration.md (+ prompt
  move). No remaining "initial-sync wizard" phrasing in README.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. Pathspec-scoped commit of ONLY those two files + prompt move, `docs:` message. Retry once on
   index lock. Never `git add -A`. Never push.
