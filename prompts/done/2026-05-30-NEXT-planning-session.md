---
name: 2026-05-30-NEXT-planning-session
status: completed        # pending | completed | failed
created: 2026-05-30
model: opus              # opus = research/planning, sonnet = coding
completed: 2026-05-30    # filled when the work is done
result: Session re-oriented on project state; prompt archived (planning closed out by user request).
---

# Task: Planning session — orient on filament-bridge, scope the next phase

This is a **planning/handoff brief**, not a coding task. Its job is to re-orient a fresh
session on where the project stands and to **decide + produce the next handoff prompt(s)**
via the project's prompt process. Read, verify state, pick the next phase with the user,
then write the execution prompt(s).

## Before you start

- **Read `CLAUDE.md`** (project rules, env, structure) and **`docs/prd.md`** (FRs, P0/P1/P2).
- **Read `docs/decisions.md`** — especially the four `2026-05-30` entries (compose/SPA fixes,
  Phase 5 sync fixes, multicolor mapping) and the Phase 3/3b/4 entries.
- **Read `docs/reconcile-backlog.md`** — the live-run punch list (items 1–5).
- **Skim `prompts/done/`** for the build history (foundation → Phase 1 → 2 → 3 → 3b → 4 →
  Phase 5 sync fixes), and `prompts/` for anything still pending.
- Use the `vexp` `run_pipeline` MCP tool for code context, not grep/glob.
- **Bring up the stack and check reality** before planning:
  `mkdir -p private_data/{filament-bridge,filament-db,spoolman}` (first time) →
  `docker compose -f docker-compose.dev.yml up -d --build` → hit
  `http://localhost:8090/api/sync/status`. Real test data: restore
  `private_data/spoolman-livedata.db` into `private_data/spoolman/spoolman.db`
  (stop spoolman → copy → start). UI also runnable in hot-reload dev mode (uvicorn +
  `backend/.env` → `localhost:3000`/`7912`; Vite on a free port, default 5173 may be taken).

## Where the project stands (as of 2026-05-30)

- **P0 backend — complete.** Persistence, continuous sync engine (snapshot/diff/match/apply/
  conflict/log, FR-8…FR-14), and the initial-sync wizard incl. execute (FR-1…FR-7). 85+
  backend tests.
- **P1 Web UI — complete.** React SPA: dashboard, synced records, conflicts, sync log,
  settings, 6-step wizard. Served same-origin from `/static`; SPA route fallback fixed.
- **Deployable.** `docker-compose.yml` (named volumes) and `docker-compose.dev.yml` (local
  bind-mounts under gitignored `private_data/`) both bring up bridge + Filament DB + Mongo +
  Spoolman. Images are on **GHCR**; Spoolman pinned to `SPOOLMAN_PORT=7912`.
- **Sync correctness (Phase 5) — done.** First live run (223 spools) drove fixes: Spoolman
  **PATCH not PUT**, configurable **weight precision** (default 2 dp), missing-material
  default, `wizard_completed` only flips on zero failures.
- **Multicolor mapping — specced + prompt ready** (`prompts/...multicolor-colorname-mapping.md`).
  Status to confirm: may be done/pending depending on whether it was run.

## Candidate next phases (planner scopes ONE+ into prompts, with the user)

1. **Reconcile-phase UI (FR-4) — the big one.** Build the match/reconcile UI for
   `docs/reconcile-backlog.md` items 1–4: filament **name-collision** disambiguation (43 ×
   409 — rename/merge/skip), **empty-but-active spools** (63 — import/skip/archive),
   **default-tare** confirmation (79 — FR-5 override surfacing), and **variant grouping on
   fresh import**. This is the natural next major phase; name collisions are the highest-value
   piece.
2. **Multicolor** — if its prompt hasn't been run/merged yet, sequence it.
3. **P2 features (FR-20–FR-25):** Discord notifications (FR-20, `discord_webhook_url`
   already parsed — half-wired), archive/retire sync (FR-21), print-history enrichment
   (FR-22), bulk ops (FR-23 — `conflicts/bulk-resolve` exists; bulk variants/tare don't),
   backup/restore + config export UI (FR-24/25 — backend exists).
4. **Quality / release-readiness:** frontend has **no tests and no CI**; the Docker image
   was built but not run in CI; a first **release** has never been cut (the project adopts
   `release-prep`/`release-cut` but nothing is tagged).

## Gotchas to carry into planning (don't rediscover)

- **Deep-link icons** use `systems[*].url` from `/health` — docker-internal hostnames in
  compose, so they don't click through on a localhost-only run; they work on a real LAN
  deployment (or in host dev mode). Not a bug.
- **Filament DB:** unique filament **name** (the collision source); **single color** + the
  `settings{}` bag is **off-limits** (its UI "Notes" = `settings.filament_notes`); no
  version endpoint (health shows `version: null` — expected).
- **Spoolman:** **PATCH** for spool updates; extra fields hold the cross-ref IDs and are
  JSON-double-quoted; `?limit=1000` to get all spools; archived spools are returned and
  filtered client-side.
- **Test data:** `private_data/spoolman-livedata.db` is the clean 223-spool snapshot; re-seed
  it to reset for a clean run.

## When done (this planning session)
1. With the user, **decide the next phase**; record any non-obvious calls in
   `docs/decisions.md`.
2. **Write the next handoff prompt(s)** from `prompts/TEMPLATE.md` into `prompts/` (one file
   per scoped task; `model: sonnet` for coding).
3. Update this file's frontmatter (`status: completed`, `completed`, `result`) and
   `git mv` it into `prompts/done/`.
4. Propose a commit for the new prompt(s) + any doc updates (no `Co-authored-by:`); present
   the file list and ask before staging. Commit on `dev`; no push.
