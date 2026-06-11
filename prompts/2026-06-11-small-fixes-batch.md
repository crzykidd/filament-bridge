---
name: 2026-06-11-small-fixes-batch
status: pending
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Small-fix batch from the 2026-06-11 full-code audit

Small, independent fixes (`prompts/assets/2026-06-11-docs-gap-report.md`, B5/B7/B9 +
minors). Each is a few lines; do them all in one pass, one commit.

## 1. Wrong published image in docker-compose.yml (B9 — user-facing!)

`docker-compose.yml` line 7 says `image: ghcr.io/hyiger/filament-bridge:latest`.
`hyiger` is the Filament DB author — the bridge publishes to
**`ghcr.io/crzykidd/filament-bridge`** (see `standards.md` code-checkin row and
`.github/workflows/publish.yml`). Fix the image reference. Grep the repo for any other
`hyiger/filament-bridge` occurrences (the README was already fixed in the docs overhaul).

## 2. Dashboard `next_sync_at` ignores the runtime interval (B5)

`api/sync.py:sync_status` computes
`next_sync_at = last_sync_at + timedelta(seconds=settings.sync_interval_seconds)` — the
ENV default, not the runtime-effective value. Use
`_effective_sync_interval(db)` from `api/config.py` instead.

## 3. Dead docs link in Settings (B6) — handled elsewhere

The `/docs/variant-parent-mode` link in Settings is fixed by the dedicated in-app docs
prompt (`prompts/2026-06-11-serve-docs-in-app.md`), which makes `/docs/<slug>` real.
Skip it here.

## 4. Spoolman pagination cap (B7)

`services/spoolman.py` `get_spools`/`get_filaments`/`get_vendors` fetch a single page with
`limit=1000`; larger libraries are silently truncated. Implement simple offset pagination:
loop `limit=1000, offset=n*1000` until a short page returns; concatenate. Keep one helper
to avoid triplicating the loop. Add a unit test with a mocked client returning 1000 + 5
records across two pages.

## 5. Settings interval copy mismatch

`Settings.tsx` Scheduler & Logs says "Minimum 30 seconds (0.5 min). Takes effect
immediately…" but the input's minimum is 1 minute (values are whole minutes). Change the
copy to "Minimum 1 minute. Takes effect immediately without a restart." (The backend's
30 s floor only matters for API callers.)

## 6. Dashboard dry-run consistency with wizard settings

`core/dryrun.py:plan_dry_run` calls `_plan_spoolman_to_fdb` without
`include_empty_spools` (so empties always preview as creates even when
`never_import_empties` is on) and without `variant_keywords`. Read both from BridgeConfig
the same way `api/wizard.py:wizard_preview` does (`never_import_empties` →
`include_empty_spools=not value`; `_resolve_variant_keywords`-equivalent) and pass them
through, so the Dashboard dry-run matches the wizard preview.

## Tests

- Unit-test #4 (pagination) and #6 (dry-run respects `never_import_empties`).
- #2: status response uses the DB-overridden interval when set.
- Frontend: `npm test` + `tsc` clean for the Settings copy/link changes.
- Full backend suite green.

## Working tree check

Run `git status --porcelain` first. A large uncommitted docs batch (README, docs/*,
CLAUDE.md, prompts/*) is expected — leave it alone. If any of the files above are dirty,
stop and ask.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. One `docs/decisions.md` entry summarizing the batch (the compose-image fix deserves an
   explicit line).
3. Propose ONE commit (`fix:` prefix, no Co-authored-by), on `dev`.
