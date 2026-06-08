---
name: 2026-06-08-readme-alpha-banner
status: done
created: 2026-06-08
model: sonnet
completed: 2026-06-07
result: Added alpha banner blockquote under the title and a ## Backups section after ## Why? covering all three systems. Committed as docs: alpha warning banner + Backups section.
---

# Task: README alpha banner + Backups section (pre-release data-safety)

Documentation-only. Add a prominent ALPHA warning and a Backups section to `README.md`. ONE
`docs:` commit. Touch ONLY `README.md` (+ the prompt move).

## 1. Alpha banner — at the very top of the README

Immediately under the title (before any other content), add a prominent, hard-to-miss warning
blockquote, e.g.:

```
> ## ⚠️ ALPHA — back up your databases before any writes
>
> filament-bridge is **alpha** software that writes to both **Spoolman** and **Filament DB**.
> **Before** running the initial-sync wizard, applying an OpenTag cleanup, or enabling
> auto-sync, **back up all three databases** (Spoolman, Filament DB, and the bridge). See
> [Backups](#backups). Test against non-critical data first.
```

Keep wording tight and alarming-but-professional. Make sure the `[Backups](#backups)` anchor
matches the section heading added below.

## 2. Backups section

Add a `## Backups` section (place it near the top — right after the banner/Why, before deep
config, so it's seen early). Cover all three systems with accurate, copy-pasteable commands:

- **Spoolman** — trigger a safe server-side backup via the API (no need to stop Spoolman; it
  copies the DB into Spoolman's own `backups/` folder inside its data volume):
  ```
  curl -X POST http://<spoolman-host>:7912/api/v1/backup
  ```
  Note that this writes into Spoolman's volume — make sure that volume is itself persisted/
  copied. Docs: https://donkie.github.io/Spoolman/#operation/backup_backup_post
- **Filament DB** — no backup API (it's MongoDB). Back up at the database level, e.g.:
  ```
  docker exec <mongo-container> mongodump --archive=/data/db/fdb-$(date +%F).archive
  ```
  (or snapshot the Mongo volume / use your Mongo host's backup). `GET /api/spools/export-csv`
  exists but is a spools CSV export, NOT a full backup.
- **filament-bridge** — export the bridge's own state (mappings, snapshots, conflict queue):
  ```
  curl http://<bridge-host>:8090/api/backup/export -o bridge-backup.json
  ```
  Restore with `POST /api/backup/import`.

Add a one-line note that the bridge keeps auto-sync OFF by default and never deletes upstream
records without explicit action — but a backup is still the safe move during alpha.

## Verification

- No code touched. `git diff --stat` shows only `README.md` (+ prompt move).
- The banner renders at the very top; the `#backups` anchor resolves to the new section.

## When done

1. Frontmatter; `git mv` to `prompts/done/`.
2. Stage ONLY `README.md` + the moved prompt; commit on `dev` with one `docs:` message
   (e.g. `docs: alpha warning banner + Backups section`). Pathspec-scoped commit; retry once on
   index lock. Never `git add -A`. Never push.
