---
name: 2026-06-10-release-prep-docs-overhaul
status: completed
created: 2026-06-10
model: opus            # deep-dive audit + high-quality copywriting — plan/write on Opus
completed: 2026-06-11
result: Full-code audit + gap report (prompts/assets/2026-06-11-docs-gap-report.md); PRD/README rewritten, docs area built out (sync-model, wizard, conflicts, opentag, index), 5 fix prompts + tooltip prompt queued. Uncommitted per session flow.
---

# Task: Deep-dive docs audit, then rewrite PRD + README to reflect reality (release prep)

The bridge has evolved far beyond what `docs/prd.md` and `README.md` currently describe; we're
preparing for a release and want the docs to tell the truth, cleanly.

## HANDOFF CONTEXT (read first — written 2026-06-11 for a fresh model)

`docs/decisions.md` is the source of truth for *why* every recent change was made — read the
**2026-06-10 and 2026-06-11** entries at the top; they cover everything below.

**Shipped this session (on `dev`, committed) — the docs must reflect these as REAL/current:**
- Two-axis sync (direction + conflict_policy per data category) — `core/sync_policy.py`.
- Native shared-filament scalar sync: `material→type`, `density`, `diameter`,
  `spool_weight→spoolWeight`, `weight→netFilamentWeight` (Phase A) + `conflict_type` column.
- `master_divergence` conflicts + resolve→apply workflow with 3 actions (apply_all /
  variant_override / ignore) + `GET /conflicts/{id}/divergence-context` (Phase B).
- Engine **purges stale orphaned mappings** during sync when there's no live linked counterpart
  (deletion conflict only when a live, still-linked record exists).
- Wizard planner **validates mappings against live FDB** (recreates stale instead of skipping).
- Created FDB filament/variant **naming = vendor + material + color** (e.g. "Hatchbox PLA Light
  Blue"); marker only on the master — fixes 409 name collisions.
- **`POST /api/debug/full-reset`** (bridge DB + Spoolman cross-refs in one call); the two older
  one-sided debug cleanups were relabeled.
- Wizard Execute step now surfaces **per-record failures (label + error)**; `WizardExecuteRecord`
  gained a `label` field.
- "See conflict" deep-link Synced Records → Conflicts (`MappingRow.conflict_id` + `?highlight=`).
- Dark-mode fix on the Bulk Import Preview step.
- Version hard-gating: known upstream below `MIN_FDB` (1.33.0) / `MIN_SPOOLMAN` (0.22.0) disables
  sync (`core/version.py`); README prerequisites section must say *enforced*, not advisory.

**NOT yet built — do NOT document as shipped:**
- **`changes.log`** durable mutation file — only a *pending* prompt
  (`prompts/2026-06-10-changes-log-file.md`); not implemented. Omit from the docs (or mention
  only as roadmap if the user asks).

**Uncommitted in the working tree:** `README.md` has a half-done edit to the Prerequisites
section (enforced minimums + "1.37.0 latest tested"). **Fold it into the full README rewrite** —
don't treat it as a separate change.

Original sequencing note (now moot — proceed when the user says go).

## Phase 1 — Deep-dive audit (produce a gap report first; do NOT rewrite yet)

Read the actual implementation and compare against the docs. Cover at least:
- **PRD (`docs/prd.md`)** — go through every FR-*; mark each as: implemented-as-described /
  implemented-but-changed / not-yet / removed. Note features that exist in code but are absent
  from the PRD (e.g. two-axis direction+policy sync, native shared-field sync + master-divergence
  resolution, full reset, vendor+material+color naming, import-failure visibility, OpenTag
  cleanup, API token auth, version hard-gating, changes.log, etc.).
- **README (`README.md`)** — every section vs reality: prerequisites/enforced versions, env-var
  table, settings, wizard flow, sync model, conflicts, deep links, deployment.
- **Other docs** — `docs/spoolman-writes.md`, `docs/decisions.md` (source of truth for the "why"),
  `docs/variant-parent-mode.md`, `docs/migration-*.md`, `CLAUDE.md` env-var + structure tables.
- Cross-check env vars / runtime settings in `backend/app/config.py` + BridgeConfig against the
  README/CLAUDE tables (drift is likely).
Output: a concise gap report (what's stale, missing, wrong) to drive Phase 2. Surface it for the
user before the rewrite.

## Phase 2 — Rewrite (after the gap report is reviewed)

- **PRD:** bring it up to date — reconcile FR status, add the shipped-but-undocumented features,
  mark superseded items. Keep it a spec, not a changelog.
- **README:** full refresh to reflect reality. **Clean, neat, and written like a seasoned
  copywriter** — tight, confident, skimmable prose; good headings; accurate examples; no
  redundancy or filler; lead with what the bridge is and why, then how to run it, then the
  feature surface. Fix the prerequisites section (enforced minimums = sync hard-gate; recommended
  = latest tested) and **fold in the already-staged uncommitted README version edit** rather than
  treating it separately.
- Keep `docs/decisions.md` as the rationale log (don't duplicate it into the README).

## Conventions
- Docs ship per `code-checkin-and-pr`; if this lands with code it shares the commit, else a
  `docs:` commit. This is release-prep groundwork — the actual version bump/changelog is the
  separate `/release-prep` flow, do NOT do that here.
- Confirm the gap report with the user before committing the rewrite.

## When done
Update frontmatter; `git mv` to `prompts/done/`; report. (Commit handling per the session flow.)
