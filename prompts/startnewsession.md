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

## ⏸️ PICK UP HERE (paused 2026-07-12, mid-session, host reboot)

**Where things stand — repo is synced, one feature awaits release:**
- On branch `dev`, HEAD = **`ebd474a`** (`feat: let users pick which FDB filaments to
  bulk-import into Spoolman`, **issue #69**). **Pushed** — `dev` == `origin/dev`, `main` ==
  `origin/main`, clean tree. Nothing stranded. The feature is committed but **not yet
  released**. First thing on return: cut **0.6.15** for it (`/release-prep 0.6.15` → merge
  the PR when CI is green → `/release-cut 0.6.15`).
- That feature (the last thing built): FDB→Spoolman wizard now has a per-record "create in
  Spoolman" checkbox for unmatched Filament DB filaments (unchecked by default — check to
  include; masters non-selectable), instead of auto-importing all. Backend
  `wizard_fdb_import_selection` + `_execute_fdb_to_spoolman(fdb_create_ids=…)`; single-record
  import (Conflicts "Add") + engine auto-import unchanged (`fdb_create_ids=None`=create all).
  Tests green (backend 1425 + ruff; frontend 188 + tsc). Docs + CHANGELOG done.

**The FDB→Spoolman import saga (this session) — all shipped except #69:** importing a Filament
DB master+variant into Spoolman was broken in *four* stacked layers, fixed one per release:
- **#61** (v0.6.12): create payload omitted required `diameter`/`density` → 422; also skip
  synthetic "masters" (they don't sync to Spoolman's flat model).
- **#62** (v0.6.12): auto-sync PATCHed null `density`/`diameter` → 422 every cycle.
- **#64** (v0.6.13): the Conflicts "Add" **preview was writing to Spoolman** (dry-run called
  the real importer, only rolled back SQLite). Real `dry_run` mode added. **#65 still OPEN** —
  the SM→FDB direction has the same latent preview-writes bug (masked by find-or-attach;
  needs the same `dry_run` on the bigger `_execute_spoolman_to_fdb`).
- **#67** (v0.6.14): filament created without `weight` → Spoolman rejected the spool
  (`remaining_weight` needs a filament weight) → 400. weight = max(netFilamentWeight, largest
  spool net) so overfilled spools aren't clamped; self-heals weight-less filaments on re-import.
- **#69** (unreleased, `ebd474a`): the selectable-import UI above.
- **Prod cleanup done:** deleted orphan Spoolman filaments the buggy preview created
  (`spoolman.crzynet.com` #178/#179 masters). Verified fixes e2e against live crzydev
  (FDB 1.66.1 / Spoolman 0.24.0) with real bridge code + cleanup.

## Current state (update as it moves)

- Latest release: **v0.6.14** (2026-07-12) — FDB→SM spool-create 400 fix (#67). Chain:
  v0.6.13 (#64 preview-writes), v0.6.12 (#61 diameter-422 + #62 null-scalar-PATCH). Baseline
  bumped to **FDB 1.66.1 / Spoolman 0.24.0** (verified, no bridge-affecting changes). Earlier:
  v0.6.11 (repo audit — see below), v0.6.10 (Synced Records Unlink #40 *partial*; net/gross
  labels #55), v0.6.9 (mobile printer-slot #53; OpenTag clarity #52).
- Open issues (see `docs/backlog.md`): **#69** selectable FDB import — *code done, `ebd474a`
  unpushed, needs release*; **#65** SM→FDB preview-writes (same class as #64, bigger fix);
  **#40** RELINK in Synced Records (Unlink shipped v0.6.10; relink needs a
  `filament-suggestions-by-mapping` endpoint + ranked picker); **#47** read-only API token
  (design call); **#24** Discord webhooks (FR-20); **#25** print-history enrichment (FR-22,
  deferred).
- **Branch-tangle gotcha:** `/release-cut` leaves you on `main`; if you then commit, it lands
  on local `main` by mistake. After any release-cut, `git checkout dev` and
  `git branch -f main origin/main` before doing more work (happened 3× this session).
- Live prod inspection: see the `prod-bridge-instance` memory (URL + read-only API-token
  auth) and `get-only-on-production` (GET-only; the shared token is full read-write). The
  test upstreams `crzydev.home.arpa:3000` (FDB) / `:7912` (SM) are writable and were used for
  e2e — clean up any `zzz-*` test records you create.

## 2026-07-02 repo audit — shipped in v0.6.11

A three-track audit (security / Claude-token-efficiency / docs) run on 2026-07-02 and
shipped **in full** in v0.6.11. Detail lives in `docs/decisions.md` (2026-07-02 entries)
and the CHANGELOG v0.6.11 section. Summary:

- **Security:** backup secret boundary — export/import no longer leak/accept auth secrets
  (#57); proxy-aware cookie `Secure` flag (`_is_https` reads `X-Forwarded-Proto`) + uvicorn
  `--proxy-headers` + response security headers (#58); per-IP in-memory login rate-limiting
  (5 attempts → 429 + Retry-After, 5-min cooldown) (#59). **M3 accepted-risk/won't-fix:**
  plaintext secrets in SQLite are a deliberate tradeoff for the single-admin self-hosted
  model (decisions.md). Audit verified good: bcrypt+salt, timing-safe compare,
  HttpOnly+SameSite=lax cookie, `/r/` open-redirect + SPA path-traversal defenses, no raw
  SQL, no XSS sinks, non-root container.
- **Token efficiency:** CLAUDE.md slimmed 47k → 12k bytes (~75%) by moving reference
  material behind pointers; new `docs/upstream-apis.md`; `docs/decisions.md` got a
  topic-grouped index at the top — **regenerate it with `scripts/gen-decisions-index.py`
  after adding a `## ` entry (and add the heading to that script's `CATEGORIES`)**;
  `rehype-slug` wired into the in-app DocsViewer so anchors jump.
- **Docs:** security.md corrected (session lifetime via `mobile_session_days`, full
  public-routes list, the `mobile_session_days=0` public-mode exposure); new
  `docs/reconcile.md` + `docs/tare-editor.md`; orphan-spool pass row in sync-model.md;
  conflicts.md relink claim fixed; added `CONTRIBUTING.md` + `SECURITY.md`.
- **Still open (not an issue yet):** a troubleshooting/FAQ doc was scoped but not written.

## How to start a session

1. Read the docs above.
2. Ask me (the user) which bug/issue to work — then work only that.
3. Make the change with tests + docs in the same commit; run the test commands; **stop
   and ask before pushing.**
