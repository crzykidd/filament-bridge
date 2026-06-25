# Backlog & priority

Prioritized work queue from the FR review (2026-06-23). **GitHub issues are the source of
truth**; this file is the ordering we agreed to work them in. Update it as issues close.

Work top-to-bottom. Within a tier, issues are roughly independent unless a dependency is noted.

## Tier 1 — Bugs (do first)

1. ~~**[#21](https://github.com/crzykidd/filament-bridge/issues/21)** — `cross_system` conflict resolve re-queues next cycle.~~ ✅ **Fixed on `dev`** (`af9028d` per-row + `5fd1283` bulk-resolve): `apply_cross_system_conflict` writes the chosen value to both sides + refreshes both snapshots for every field family; weight is a direct absolute write; bulk-resolve converges with per-conflict failure isolation. Closes on the next release PR (`Fixes #21`).
2. ~~**[#22](https://github.com/crzykidd/filament-bridge/issues/22)** — sync-log retention only prunes on auto-sync ticks; never prunes when auto-sync is off.~~ ✅ **Fixed on `dev`**: new `prune_sync_log_now(db)` wrapper (reads retention, prunes, commits, error-tolerant) is called from the manual sync trigger (`POST /sync/trigger`), the nightly backup job (before its master-switch gate), and once at startup — so retention applies regardless of auto-sync state. Closes on the next release PR (`Fixes #22`).

## Tier 2 — Wizard UX behavior changes

3. **[#13](https://github.com/crzykidd/filament-bridge/issues/13)** — require tare entry when unknown (drop the 200 g default; blank required field, block Execute).
4. ~~**[#26](https://github.com/crzykidd/filament-bridge/issues/26)** — standalone bulk tare editor.~~ ✅ **Done on `dev`**: new **Tare Editor** page + `GET /api/tare` / `POST /api/tare/bulk`. Lists mapped filaments with both-side tare, flags missing/mismatch, per-row + multi-select bulk set; writes both sides and refreshes both `_mp_spool_weight` snapshots (reuses `core/tare.py`, no duplicated weight logic). Variants read-only (inherited). Closes on the next release PR (`Fixes #26`).
5. **[#14](https://github.com/crzykidd/filament-bridge/issues/14)** — partial-success completion + persistent Failure Report (don't block on per-record failures).

## Tier 3 — Docs (PRD-sync — one PR closing all six)

6. **[#15](https://github.com/crzykidd/filament-bridge/issues/15)** FR-8 settings-list dedup ·
   **[#16](https://github.com/crzykidd/filament-bridge/issues/16)** FR-9 weight-increase path ·
   **[#17](https://github.com/crzykidd/filament-bridge/issues/17)** FR-11 material passes + FDB→SM gate (+ FR-23b Apply note) ·
   **[#18](https://github.com/crzykidd/filament-bridge/issues/18)** FR-12 new-record policies ·
   **[#19](https://github.com/crzykidd/filament-bridge/issues/19)** FR-13 auto-resolve clarifications ·
   **[#23](https://github.com/crzykidd/filament-bridge/issues/23)** FR-19 mapping edit/unlink + detail.
   - Sweep in the cosmetic FR-27 nit (stale `0.2.0`/`0.3.0` sample JSON in `version-update-check.md`).

## Tier 4 — Features / enhancements

7. **[#24](https://github.com/crzykidd/filament-bridge/issues/24)** — Discord webhook notifications (conflicts / errors / optional daily summary).
8. **[#20](https://github.com/crzykidd/filament-bridge/issues/20)** — surface backup status (last/next scheduled backup) in the UI (+ show UTC hour's local equivalent).

## Tier 5 — Deferred (revisit on demand)

- **[#25](https://github.com/crzykidd/filament-bridge/issues/25)** — print-history enrichment (waiting on a clean job-metadata source).
- Bulk **variant** assignment outside the wizard (FR-23) — wizard-only for now; not yet filed.

## Shipped this cycle

- **[#5](https://github.com/crzykidd/filament-bridge/issues/5)** — scheduled nightly backups (FR-24b). Merged to `dev`; closes via the next release PR (`Fixes #5`).
