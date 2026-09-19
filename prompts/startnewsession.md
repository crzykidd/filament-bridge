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

## ⏸️ PICK UP HERE (paused 2026-09-19, clean — v0.6.22 shipped)

**Everything is released and synced — nothing in flight, nothing stranded.**
- **v0.6.22 is live** (tag `v0.6.22`, GitHub release published, prod image build **succeeded** —
  `:latest` / `:0.6.22` / `:0`). PR #92 (`dev → main`) merged; `main` == `origin/main`; `dev` ==
  `origin/dev`; clean tree; **nothing unpushed**. On return you're on `dev`. (Reminder: main
  accumulates the PR merge commits, so `dev..main` shows a handful of commits — that's expected
  divergence, content is identical.)
- **v0.6.22** shipped **#89** + **#90** (both closed), the two findings from the 2026-09-18 compat
  review — see that bullet below for the analysis. **#89:** `_sync_opentag_identity` is no longer
  stateless — a per-side `_opt_uuid`/`_opt_slug` baseline lives in the existing **filament-level**
  `Snapshot` row (same mechanism as the multicolor `_mc_sig` / cost passes, so **no migration**).
  A side whose baseline HELD a value and is now empty = a deliberate unlink → the removal
  **propagates** to the other side (direction-gated, reusing the `remove_filament_settings_keys()` /
  SM extra-blank primitives the OpenTag Cleanup unmatch already uses); an **absent** baseline + empty
  side still **fills** (deliberately NOT the multicolor "first sight → store, no write" rule, which
  would regress #81). Baselines also refresh on the QUEUE_CONFLICT path so a later clear reads as
  "had a value". 15 tests in `test_engine_opentag_identity.py`. Decisions.md 2026-09-18 entry.
  **#90:** `ensure_fdb_location` trims the lookup key, cache key and create (+ the three inline
  cache builders); the FDB-side location snapshot records the **trimmed** value FDB actually stored
  while the SM side keeps its raw value; and the both-sides-changed convergence check compares via
  `_norm_str` (strip only — deliberately **no** case folding, since FDB's uniqueness is on the
  trimmed value). All three parts were required: part 1 alone turns the error loop into a ping-pong
  loop.
- **v0.6.21** shipped **#87** (closed): FDB→SM new-spool detection keyed on the user-set `label`
  instead of the GUID. `label` is user data (e.g. FDB 1.73.0's "Next #" button) and the bridge only
  ever filled it when blank, but detection treated ANY non-empty `label` as "already synced", so a
  hand-labeled spool was never created in Spoolman. Detection now skips only on a `SpoolMapping` or
  a GUID already in some Spoolman spool's `filamentdb_spool_id` extra (lost-mapping orphan, not a
  duplicate); the SM-ID writeback (engine + wizard) is now conditional on `label` being blank.
  `test_fdb_label_guid_detection.py`. Decisions.md 2026-08-08 entry.
- **v0.6.20** shipped **#83** (closed): stale `new_filament` conflicts no longer linger for
  filaments whose spools are all archived/retired. The stale-conflict cleanup pass in
  `core/engine.py` (~3172) handled only `new_spool`; a `new_filament` conflict for a filament whose
  only Spoolman spool went **archived** (or only FDB spool went **retired**) sat in the queue
  forever with no import path. Two-part fix: (1) **reactive** — the cleanup pass now auto-resolves
  (`resolved_not_imported`) an open `new_filament` conflict once its filament has **no active
  spool** (keyed by `spoolman_id` → checks `archived`, or `filamentdb_filament_id` → checks
  `retired`); **purely lifecycle-state based — a 0 g spool still counts as active and keeps the
  conflict** (deliberately does NOT consult `never_import_empties`/weight, unlike the adjacent
  `new_spool` block). (2) **preventive** — the FDB→SM new-spool detection loop (~4234) now skips
  retired FDB spools (mirrors the SM side's active-only feed). Safe by construction: `new_filament`
  ⇒ unmapped/never-synced, so the mapped-pair lifecycle pass is untouched; self-heals on restock.
  6 tests in `test_stale_new_filament_cleanup.py`. Decisions.md 2026-07-31 entry.
- **v0.6.19** shipped **#81** (closed): OpenPrintTag identity sync made **bidirectional**.
  `_sync_opentag_identity` (core/engine.py) was one-way (Spoolman→FDB), so a filament matched to
  OpenPrintTag *natively on the FDB side* (`settings.openprinttag_slug`/`uuid`) never flowed back
  to Spoolman → OpenTag Cleanup saw it as unmatched. Now a **stateless bidirectional
  reconciliation keyed on `openprinttag_uuid`**: whichever side has an identity fills the empty
  side (FDB writes still ONLY via the scoped `merge_filament_settings()` exception), a genuine
  `uuid` divergence **queues a deduped `cross_system` conflict** (`field_name="OpenPrintTag
  identity"`) instead of overwriting. Direction-gated on the `material_properties` axis
  (`resolve_sync_action`, dir value `"two_way"`). Dry-run aware. Verified with a **live E2E**
  against the dev upstreams (FDB→SM fill / idempotent / divergence→conflict-no-overwrite /
  direction-gating all pass; `zzz-*` test records cleaned up). 7 unit tests in
  `test_engine_opentag_identity.py`. Decisions.md 2026-07-27 entry.
- **Upstream compat reviewed 2026-09-18 — BOTH upstreams; both findings (#89, #90) SHIPPED in
  v0.6.22; follow-up #91 open.** FDB
  latest **1.82.0**, Spoolman latest **0.26.1** (Spoolman had never had a dedicated review; the
  prior reference was 0.23.1). Full detail in decisions.md 2026-09-18.
  - **#89** — FDB **1.77.0** (`#1150`) added *Change link* / *Remove link* to the OpenPrintTag
    dialog: the first FDB-side way to CLEAR a link. `_sync_opentag_identity` is **stateless (no
    baseline)** and fills whichever side is empty, so a deliberate unlink is **refilled next cycle**
    — silently undone, repeatedly. *Change* is fine (divergence still queues a `cross_system`
    conflict). Fix needs a **design call**: a per-mapping baseline of the last-synced identity to
    tell "never linked" from "cleared" (then propagate the clear via the scoped
    `remove_filament_settings_keys()`).
  - **#90** — FDB **1.76.0** (`#1116`) added `trim: true` to `name` on the five uniquely-named
    models **plus a migration that trims stored names**. `ensure_fdb_location`
    (`core/locations.py`) matches byte-exactly and creates with the raw Spoolman string, so an
    untrimmed Spoolman location misses its trimmed FDB row → the create **collides on the unique
    name → 4xx, every cycle** (caught at `engine.py:3907`, that spool's location never syncs). The
    upgrade itself is the likely trigger — the bridge created those untrimmed names. Fix = trim the
    cache key AND the create in the one shared helper (covers engine, conflict_apply, wizard,
    mobile) + a regression test.
  - **Verified safe:** Spoolman 0.26.0's trusted-origin guard trusts an **absent** `Origin` (our
    httpx clients send none) and its host guard is **opt-in**; 0.26.1 (`#987`) uppercases colour hex
    on read but every comparison path already normalises case (`differ.normalize_color`,
    `multicolor_signature`); extra-field caps (64 KiB/value, 128/entity) are far above what we
    write; we open **no websockets**. FDB 1.78.0 settings arrays stay lossless through our opaque
    whole-bag read-modify-write; migrated legacy single-spool rolls take the normal GUID-keyed
    new-spool path; 1.79.0 print-job debits/refunds map onto the existing decrement and
    weight-increase paths; 1.80.0–1.82.0 are outside our surface. **1.81.1 ships Next.js 16.3.4 for
    two CRITICAL RCE advisories — worth upgrading FDB for on its own merits.**
  - Prior reviews: 2026-08-08 (≤1.75.0) filed **#86**; 2026-08-02 (≤1.72.0) filed **#85**. `MIN_FDB`
    1.33.0 / `MIN_SPOOLMAN` 0.22.0 unchanged.
- **v0.6.18** shipped **#78** (Bulk Import Wizard Variances resolves an existing FDB master's
  tare — `resolve_family_tare` via shared `matcher.build_family_tare_by_sm_id`, `tare_source
  "filamentdb_master"`) + **#79** (Mobile Updates lookup defaults to numeric keypad with `#`/`Abc`
  toggle). **v0.6.17** shipped **#76** (master-level group defaults: seed-on-create + Master
  Defaults backfill screen at `/master-defaults` + Conflicts "Add" tare pre-fill; FDB 1.68.1
  compat; CI ruff pinned to 0.15.17).

**Open / next work (ALWAYS ask the user which to take before starting):**
- **#91** — *fallout from #89, found reviewing it.* Now that the engine can converge an OpenTag
  identity divergence **by itself** (a clear propagates, leaving both sides empty), the
  `cross_system` conflict queued for that pair is never auto-resolved — it lingers describing a
  divergence that no longer exists, **and** `_has_open_conflict` then suppresses any future identity
  conflict for that pair until a human clears it. The stale-conflict cleanup (`engine.py:3129`) is
  scoped to `entity_type="spool"` / `new_spool` (+ #83's `new_filament`); the engine's only other
  auto-resolutions are `auto_stale_purge` and `auto_resolved_reappeared`. Same *class* as #83. Fix =
  auto-resolve the identity conflict when the pass observes both sides converged
  (`auto_resolved_converged` + a sync-log row, dry-run aware) — and first **audit the other
  `cross_system` producers** (weight, location, material props) for a divergence-vanishes-by-itself
  path, which decides whether the fix belongs in the identity pass or in a shared convergence check.
  **Only ever close conflicts whose two values became equal — never auto-resolve a real divergence.**
- **#85** — parent-exclusion guards key on `is_synthetic_parent`, not `is_master_fdb`; a real
  FDB-native parent mapped to Spoolman then promoted to a 1.70.0 template gets rejected color/spool
  writes. Fix = switch the guards at `engine.py:1071` (multicolor push) + `engine.py:2787`
  (new-spool create) to `is_master_fdb` + a regression test. Edge case; surfaced 2026-08-02.
- **#86** *tracking, LOW PRIORITY* — FDB 1.75.0 (`#1072`) capped the generic filament PUT settings
  bag (400 keys / 20 000 chars); the OpenTag settings writers re-send the whole bag, so an oversized
  slicer bag could 400 the write. Fix = catch the 400 in `merge_filament_settings` /
  `remove_filament_settings_keys` (`services/filamentdb.py:216-280`), log a clean `skip`, continue.
  No observed failure; don't schedule ahead of active work.
- **#73** *optional remainder* — background the blocking "Sync now" cycle **only if** it turns out
  to be *timing out* rather than erroring (the new structured 500 will confirm which). Not worth
  doing speculatively.
- **#40** RELINK in Synced Records (Unlink shipped v0.6.10; relink needs a
  `filament-suggestions-by-mapping` endpoint + ranked picker); **#47** read-only API token
  (design call); **#24** Discord webhooks (FR-20); **#25** print-history enrichment (FR-22,
  deferred).

**The FDB→Spoolman import saga — ALL SHIPPED:** importing a Filament DB master+variant into
Spoolman was broken in stacked layers, fixed one per release:
- **#61** (v0.6.12): create payload omitted required `diameter`/`density` → 422; also skip
  synthetic "masters" (they don't sync to Spoolman's flat model).
- **#62** (v0.6.12): auto-sync PATCHed null `density`/`diameter` → 422 every cycle.
- **#64** (v0.6.13): the Conflicts "Add" **preview was writing to Spoolman** (dry-run called
  the real importer, only rolled back SQLite). Real `dry_run` mode added (FDB→SM direction).
- **#65** (v0.6.16): the SM→FDB direction had the *same* latent preview-writes bug — fixed by
  giving `_execute_spoolman_to_fdb` a real `dry_run` (all 15 upstream writes guarded).
- **#67** (v0.6.14): filament created without `weight` → Spoolman rejected the spool
  (`remaining_weight` needs a filament weight) → 400. weight = max(netFilamentWeight, largest
  spool net) so overfilled spools aren't clamped; self-heals weight-less filaments on re-import.
- **#69** (v0.6.15): the selectable-import UI (per-record "create in Spoolman" checkbox).
- **#70** (v0.6.15): adding a filament crashed with `UNIQUE constraint failed:
  filament_mappings.spoolman_filament_id`. Root cause = **Spoolman reuses deleted integer ids**
  (SQLite rowid, no AUTOINCREMENT), so a stale bridge mapping left by an earlier orphan-cleanup
  collided with a freshly-created filament handed the reused id. Two-part fix: (1) the FDB→SM
  create path clears a stale mapping on the just-minted id; (2) root cause — the sync cycle
  **purges a filament mapping the cycle its Spoolman filament is deleted**
  (`_purge_stale_filament_mappings` in engine.py). Deliberately does NOT auto-purge on identity
  mismatch (would false-positive on user-renamed filaments). See decisions.md 2026-07-19.

## Current state (update as it moves)

- Latest release: **v0.6.22** (2026-09-19) — #89 a deliberate OpenTag unlink now propagates instead
  of being refilled next cycle (the pass is baselined), + #90 FDB location names are matched and
  created trimmed, so an untrimmed Spoolman location no longer errors every cycle.
  Prior: v0.6.21 (2026-09-18) — #87 FDB→SM new-spool detection keys on the FDB spool
  GUID, not the user-set `label`, so a hand-labeled spool is no longer skipped; the SM-ID writeback
  only fills a blank `label`.
  v0.6.20 (2026-07-31) — #83 stale `new_filament` conflicts auto-resolve when a
  filament has no active spool (all archived/retired); active-0g still counts as active and keeps
  the conflict; FDB→SM new-spool detection now skips retired spools.
  v0.6.19 (2026-07-30) — #81 OpenPrintTag identity sync made bidirectional
  (FDB-native matches now flow back to Spoolman; divergence queues a `cross_system` conflict).
  v0.6.18 (2026-07-27) — #78 wizard variances resolves the existing FDB
  master's tare (no more spurious "required" when attaching to a master that has one) + #79 mobile
  lookup numeric-keypad default. v0.6.17 (#76 master-level group defaults: seed-on-create +
  Master Defaults backfill screen + Conflicts "Add" tare pre-fill; FDB 1.68.1 compat; CI ruff
  pinned), v0.6.16 (#65 SM→FDB preview no-write + #72 tare-required Add + #74 label
  `spool_id`/`name` + #73 prod perf pass), v0.6.15 (#69 selectable FDB import + #70 reused-id
  crash/stale-mapping GC + FDB 1.67.0 bump), v0.6.14 (#67 spool-create 400), v0.6.13 (#64
  preview-writes), v0.6.12 (#61 diameter-422 + #62 null-scalar-PATCH). Earlier: v0.6.11 (repo
  audit — see below), v0.6.10 (Synced Records Unlink #40 *partial*; net/gross labels #55).
- Open issues (see `docs/backlog.md`): **#91** stale converged OpenTag identity conflict
  (follow-up to #89); **#85** template write-guards; **#86** settings-bag cap; **#73** *optional* — background the blocking "Sync now"
  only if it's timing out; **#40** RELINK in Synced Records (Unlink shipped v0.6.10; relink needs
  a `filament-suggestions-by-mapping` endpoint + ranked picker); **#47** read-only API token
  (design call); **#24** Discord webhooks (FR-20); **#25**
  print-history enrichment (FR-22, deferred). (#76 closed and released.)
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
