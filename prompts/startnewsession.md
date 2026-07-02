# Start-new-session prompt — filament-bridge

Paste/point me at this file at the start of a fresh session. It's a standing
onboarding brief (not a task — don't move it to `done/`). It restates the project and
the operating rules so a new session is productive even if conversation memory was
cleared.

## What this project is

**filament-bridge** is a bidirectional sync service between
[Filament DB](https://github.com/hyiger/filament-db) (Next.js/MongoDB, gross weight
model, MongoDB ObjectIds, spools embedded on filaments) and
[Spoolman](https://github.com/Donkie/Spoolman) (Python/FastAPI, net weight model,
relational Vendor→Filament→Spool with int IDs, extra-field system). It runs as a Docker
sidecar, polls both REST APIs, diffs against stored snapshots, applies non-conflicting
changes, and queues conflicts for manual resolution. **No upstream modifications** — only
documented REST APIs + Spoolman extra fields. Conflicts are never auto-resolved.

- **Stack:** Backend Python 3.12 / FastAPI, httpx, SQLAlchemy + SQLite, APScheduler,
  Pydantic v2. Frontend React 18 / TypeScript, Vite, Tailwind, React Router. Single
  Docker image (Node builds React → FastAPI serves it), single port 8090, SQLite in a
  mounted volume.
- **Cross-references:** Spoolman extra fields (`filamentdb_id`, `filamentdb_parent_id`,
  `filamentdb_spool_id`) link to FDB; FDB spool `label` stores the Spoolman spool id.
- **Variant model:** FDB has parent/variant inheritance (`parentId`, one level deep);
  Spoolman is flat one-filament-per-colour. The bridge tracks the parent via
  `filamentdb_parent_id`.

## Read first (in this order)

1. **`CLAUDE.md`** — the authoritative quick-reference (architecture decisions, env vars,
   runtime settings, weight/lifecycle/location sync rules, "what NOT to do").
2. **`docs/prd.md`** — full functional requirements (FR-numbers).
3. **`standards.md`** — the homelab standards this repo implements + pinned versions.
4. **`docs/decisions.md`** — the "why" log; check before re-deriving a design.
5. **`docs/backlog.md`** — the prioritised issue queue (GitHub issues are the source of
   truth; this file is the agreed order).

## Operating rules (honor these by default)

**Scope / what to work on**
- **Only work the bug(s)/issue(s) the user explicitly names.** Never fan out to the
  backlog, pick up other open issues, or add "while I'm here" fixes on your own. Offer
  others as a one-liner at most, then wait.
- For substantial *named* implementation work, prefer **dispatching to a Sonnet
  subagent** (Agent tool, `model: sonnet`, `isolation: "worktree"` when parallel); Opus
  orchestrates, reviews the diff, and integrates. Don't dispatch unnamed work.

**Git / check-in (the `code-checkin-and-pr` standard)**
- **Commit, but do not push** without explicit OK — even to `dev`. *Exception:*
  invoking `/release-prep` or `/release-cut` authorizes that command's own push.
- **Never push to `main`** (protected). Changes land via a `dev → main` PR with all
  required checks green. Day-to-day work is on `dev` (or a short branch off it).
- **Conventional-commit prefixes** (`feat:`/`fix:`/`chore:`/`docs:`). **No
  `Co-authored-by:` trailers.** **Docs ship in the same commit as the code** they
  describe. Never bypass hooks (`--no-verify` etc.).
- Branch-protection required checks use **bare names** (`Lint`, `Test`, …), not
  `CI / Lint`.

**Issue tracking / auto-close**
- **Every commit that resolves a tracked issue ends its body with `Fixes #N`** (one per
  issue it closes) — whether the issue was named by the user or filed from chat. This is
  required for traceability, not optional.
- For a bug reported **in chat with no GitHub issue** — **or any major issue/bug we
  discover during work** — `gh issue create` a full issue first, then reference it with
  `Fixes #N` in the fix commit body so it closes with the fix. **If you're unsure whether
  something warrants its own issue, ASK** — don't silently skip it or silently file it.
- In the **release PR body**, add one closing keyword **per issue** (`Fixes #22`,
  `fixes #26`, `fixes #31`) — keywords do NOT distribute across a list, and a squash
  merge discards commit trailers, so **the PR body is the reliable closer** (the commit
  `Fixes #N` is for traceability; the PR body is what actually auto-closes on merge).
- The CHANGELOG/release-notes entry for each issue should also name it (e.g. `Closes #36`
  / `Fixes #13`) so the issue ↔ release mapping is visible in the notes.
- For an already-closed issue lacking a version note, add a "Fixed in vX.Y.Z" comment.

**Testing (run before committing)**
- Backend: `cd backend && .venv/bin/python -m pytest` (the venv python; bare `python`
  isn't on PATH). Lint: `.venv/bin/python -m ruff check backend/`.
- Frontend: `cd frontend && npx vitest run` and `npx tsc --noEmit`.

**Releases (the `release-prep-and-cut` standard)**
- Version is stored **bare** in `backend/app/__init__.py` (`__version__`) and mirrored to
  the README badge + What's New + `CHANGELOG.md`. The `v` prefix is added in exactly one
  place: the git tag / GitHub release (done by `/release-cut`).
- `CHANGELOG.md` `## [Unreleased]` is the single source of release notes; the release PR
  body and the GitHub release body reuse the same section verbatim.
- Flow: `/release-prep <version>` (bump + roll changelog + sync docs + one
  `chore(release):` commit + push dev + open PR) → human merges + CI green + `:latest`
  published → `/release-cut <version>` (tag + GitHub release, which triggers the
  production image build). Never re-tag; pick the next version instead.

**Other standards**
- `repo-sandbox-permissions` (repo-wide): in-repo reads/edits/writes/bash run sandboxed;
  widen `allowedDomains`/`allowWrite` rather than adding `Bash(...)` allow rules.
- `handoff-prompt-workflow`: scoped tasks live in `prompts/` (from `TEMPLATE.md`),
  completed → `prompts/done/`; log non-obvious decisions in `docs/decisions.md`.

## Current state (update as it moves)

- Latest release: **v0.6.10** (Unlink a spool pairing from the Synced Records page — bridge-local,
  no upstream delete #40 *partial*; Synced Records detail Weight row now labeled (net)/(gross)
  #55; tested-upstream baseline → Filament DB 1.62.0). Recent: v0.6.9 (mobile printer-slot AMS/MMU
  assignment #53; OpenTag control clarity — "Re-match", content-aware staleness, freshness badge
  #52), v0.6.8 (OPT material properties as Spoolman custom fields #50), v0.6.7 (orphan-spool
  reconcile #48), v0.6.6 (mobile dry-cycle log #45; stable conflict ids #44).
- Open issues (see `docs/backlog.md`): **#40** RELINK in Synced Records UI — Unlink shipped
  (v0.6.10), relink still needs a `filament-suggestions-by-mapping` backend endpoint + ranked
  picker (see the #40 comment); **#47** read-only API token option (needs a design call:
  separate token vs per-token scope); **#24** Discord webhook notifications (FR-20); **#25**
  print-history enrichment decision (FR-22, deferred). Shipped: the docs/PRD-sync batch
  (#15–#19, #23), wizard UX (#13/#14), backup-status (#20), Tare Editor (#26), the
  conflict/mobile/orphan fixes (#44/#45/#48), OPT material-property tracking (#50), OpenTag
  control clarity (#52), mobile printer-slot assignment (#53), Synced Records Unlink (#40),
  and net/gross weight labels (#55).
- Live prod inspection: see the `prod-bridge-instance` memory (URL + read-only API-token
  auth) and `get-only-on-production` (GET-only; the shared token is full read-write).

## 2026-07-02 repo audit findings (work queue — update as items ship)

A three-track audit (security / token-usage / docs) on 2026-07-02 produced this
prioritized queue. Work items **one at a time** via handoff prompts in `prompts/`;
mark each line here when it ships.

**Security — high**
- [x] **H1** (done 2026-07-02, #57) `GET /api/backup/export` (and the nightly on-disk backup) serializes the
  whole `BridgeConfig` table with no denylist (`api/backup.py:238` → `api/config.py:41-43`),
  leaking `auth_secret` (cookie-signing key → session forgery), `admin_password_hash`,
  `api_token`, `labelforge_token` in cleartext JSON.
- [x] **H2** (done 2026-07-02, #57) `POST /api/backup/import` writes every `payload.config` key with no
  allowlist (`api/backup.py:256-258`) — a crafted backup can overwrite
  `admin_password_hash` / `auth_secret` (account takeover / offline cookie forgery).
  Fix together with H1: auth material never crosses the backup boundary.

**Security — medium**
- [x] **M1** (done 2026-07-02, #58) Session cookie `Secure` flag derives from `request.url.scheme`
  (`api/auth.py:112-113`) but uvicorn runs without `--proxy-headers` (Dockerfile CMD),
  so behind a TLS proxy the cookie is never `Secure`. `labels.py:67` *does* trust
  `X-Forwarded-Proto` — inconsistent. Fix: `--proxy-headers` + small security-headers
  middleware (no CSP/XFO/HSTS today; CORS default is correctly same-origin).
- [ ] **M2** No rate-limit/lockout on `/api/auth/login` (`api/auth.py:303-323`);
  `/api/auth/status` reveals whether a password is set. Matters when internet-exposed.
- [ ] **M3** (accepted-risk candidate) `api_token`/`labelforge_token` stored plaintext
  in SQLite and returned by `GET /api/config` for the Settings UI. Deliberate; revisit
  only if H1 fix doesn't feel sufficient.

**Security — low / notes**
- [x] **L1** (done 2026-07-02, folded into D1) `mobile_session_days=0` public mode allows unauthenticated weight/location
  writes, printer-slot changes, inventory enumeration, and physical label prints —
  by design, but undocumented as a security consequence (fold into D1).
- Verified good: bcrypt+salt, timing-safe token compare, HttpOnly+SameSite=lax cookie
  (CSRF-neutralizing), `/r/` open-redirect + SPA path-traversal defenses, no raw SQL,
  no XSS sinks, no tokens in localStorage, non-root container, debug endpoints
  double-gated. Deps modern.

**Token usage (CLAUDE.md ~12–14k tokens/session; target ~3.5k)**
- [ ] **T1** Replace CLAUDE.md env-var + runtime-settings tables (~4.3k tokens, 37% of
  file) with a pointer to `docs/configuration.md` (already the superset); keep only the
  2 required vars + cross-ref field defaults.
- [ ] **T2** Demote "read `docs/prd.md` before writing any code" (58 KB ≈ 14.5k tokens)
  to "consult when implementing a new FR".
- [ ] **T3** Shrink the annotated file tree (~2k tokens, already stale) to a top-level
  directory map.
- [ ] **T4** Sync internals: keep the 5 hard invariants inline (net/gross; never
  subtract usageHistory; refresh BOTH snapshots; lifecycle after weight; usage endpoint
  not weight overwrite), point to `docs/sync-model.md` for the rest.
- [ ] **T5** Move upstream API endpoint lists + gotchas to a new `docs/upstream-apis.md`
  (keep `?limit=1000` and `?allow_archived=true` inline — nastiest gotchas).
- [ ] **T6** Release-process rules are triplicated (CLAUDE.md / standards.md /
  `.claude/commands/release-*.md`) — one pointer line in CLAUDE.md suffices.
- [ ] **T7** Fence archives: one CLAUDE.md line that `prompts/done/` (1.4 MB) and
  `docs/archive/` are historical, never read unprompted; move `wizard-redesign.md`,
  `reconcile-backlog.md`, `CHANGELOG-0.x.md` to `docs/archive/`.
- [ ] **T8** `docs/decisions.md` is 304 KB (~76k tokens/lookup) — add a dated topic
  index at the top (or split by area).

**Docs**
- [x] **D1** (done 2026-07-02) `docs/security.md` stale (highest-impact doc gap): hard-coded "30-day
  session" (now `mobile_session_days`, absent from the doc); protected-routes list
  omits public `GET /api/version` and the `mobile_session_days=0` public scan surface.
  README repeats the 30-day claim. Include the L1 warning here.
- [ ] **D2** Reconcile page (`api/reconcile.py`, `pages/Reconcile.tsx`) has no current
  doc (only the historical `reconcile-backlog.md`).
- [ ] **D3** Tare Editor (`api/tare.py`, `pages/TareEditor.tsx`) has no user guide
  despite writing tare to both upstreams.
- [ ] **D4** v0.6.7 orphan-spool re-adoption pass missing from `docs/sync-model.md`
  passes table.
- [ ] **D5** CLAUDE.md drift: tree missing 20+ files; runtime-settings table missing 9
  keys (`auto_sync_enabled`, weight/material direction+policy, …); debug tools say
  three, code has four (`clear-spoolman-opentag-ids` omitted; README says three too).
  Largely absorbed by T1–T5.
- [ ] **D6** `docs/conflicts.md:181,185` claims a Relink action that was deferred
  (only Unlink shipped, v0.6.10 / #40).
- [ ] **D7** `docs/README.md` index orphans `backlog.md` (index is user-visible in-app
  via DocsViewer).
- Optional: `CONTRIBUTING.md`, `SECURITY.md` (vuln-reporting), troubleshooting/FAQ.
- Verified clean: env-var docs full parity incl. defaults; CHANGELOG consistent;
  wizard.md / mobile-updates.md / README accurate; LICENSE present.

**Agreed dispatch order:** 1) H1+H2 → 2) M1 → 3) D1(+L1) → 4) CLAUDE.md restructure
(T1–T8, absorbs D5) → 5) D2/D3/D4/D6/D7 → 6) optional M2, CONTRIBUTING/SECURITY.md.

## How to start a session

1. Read the docs above.
2. Ask me (the user) which bug/issue to work — then work only that.
3. Make the change with tests + docs in the same commit; run the test commands; **stop
   and ask before pushing.**
