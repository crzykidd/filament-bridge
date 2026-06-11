---
name: 2026-06-10-changes-log-file
status: pending
created: 2026-06-10
model: sonnet
completed:
result:
---

# Task: Durable `changes.log` file recording every write the bridge makes to Spoolman / Filament DB

## Why

When the bridge mutates an upstream system (create/update/usage/delete), the user wants a
durable, human-readable file they can open after a bad release to see exactly what changed and
fix it — independent of the SQLite DB and the UI. For updates it should show **old → new**, with
a **date/time stamp**, and which system + record was touched.

The data is already captured: the engine's `_log()` (`backend/app/core/engine.py`) writes
`SyncLog` rows with `direction`, `action`, `entity_type`, ids, `field_name`, `old_value`,
`new_value`, `error_message`, timestamp. This task adds a **file sink** that mirrors the actual
upstream mutations to a log file — it does NOT replace the `SyncLog` table / Sync Log page.

## Design (confirm open choices with the user before/while implementing)

- **Location:** append to `{DATA_DIR}/changes.log` (DATA_DIR default `/data`, the mounted volume,
  so it persists across restarts/upgrades). Make the path/enabled state overridable if cheap
  (env var, e.g. `CHANGES_LOG_PATH` / `CHANGES_LOG_ENABLED`, default on).
- **What to record:** only **successful upstream mutations** — actions `create` / `update` /
  `delete` (and weight `usage`) that actually wrote to Spoolman or Filament DB. Do NOT record
  `skip` / `info` / preview / dry-run entries, and do NOT record reads.
- **Format (recommend human-readable, one line per change):**
  ```
  2026-06-10T21:45:03Z  UPDATE  spoolman  spool #42  remaining_weight: 916.9 → 905.1   (cycle abc123)
  2026-06-10T21:45:03Z  UPDATE  filamentdb  filament 665f… "Hatchbox PLA Light Blue"  type: — → PLA
  2026-06-10T21:45:04Z  CREATE  filamentdb  filament 665f… "ELEGOO PLA Red"
  2026-06-10T21:45:05Z  USAGE   filamentdb  spool 665f…  grams: 10 (source=spoolman)
  ```
  ISO-8601 UTC timestamp; action; system; entity type + id (+ a label/name when available);
  `field: old → new` for updates; the cycle id for correlation with the Sync Log. Keep `old`/`new`
  rendered compactly (use `—` for None). **Open question for the user:** plain text (above) vs
  JSON-lines vs both — default to plain text unless they want JSONL for tooling.
- **Rotation:** append-only. Add simple size-based rotation (e.g. roll to `changes.log.1` past N MB,
  keep a couple) so it can't grow unbounded — **confirm the cap/scheme with the user**; default
  ~10 MB × 3 if unsure. Document if you leave it unbounded.
- **Robustness:** file-write failures must NEVER break sync — wrap in try/except, log a warning,
  continue. Respect the container's PUID/PGID (the data dir is already chowned by the entrypoint).

## Implementation approach

- Centralize at the audit point so every write site is covered for free. The natural hook is the
  `_log()` path: when an entry represents a real upstream mutation (action in the recorded set and
  a `direction` indicating a write), also append a formatted line to `changes.log`. Confirm `_log`
  is called at ALL upstream-write sites (engine field/weight/cost/temp/multicolor/finish/opentag
  passes, `core/conflict_apply.py` resolution writes, and `api/wizard.py` execute) — if any write
  records via a different path, route it through the same change-log helper.
- Add a small module e.g. `backend/app/core/change_log.py` with `record_change(...)` +
  rotation/formatting, reading the path/config from `app/config.py`. Keep it pure-ish and unit
  testable (allow injecting the target path / a fake clock — note `Date.now`-style nondeterminism
  must be testable; pass timestamps in or allow a clock seam).
- Decode JSON-encoded values (Spoolman extra values, snapshot values) to readable forms before
  writing.

## Before you start

- Read `CLAUDE.md` (esp. the upstream-write rules and `DATA_DIR`), `backend/app/core/engine.py`
  `_log()` and the write passes, `backend/app/core/conflict_apply.py`, `backend/app/api/wizard.py`
  execute, and `backend/app/config.py` (env parsing + data_dir).
- Check whether the new `_mp_*` / cost / naming changes already merged (this prompt runs after that
  batch) so all current write sites are covered.
- Standards: `code-checkin-and-pr`.

## Tests

- `record_change` formats update (old → new), create, delete, usage lines correctly; None → `—`.
- File is appended to (not truncated); rotation triggers past the cap.
- A write-failure (e.g. unwritable path) is swallowed and does not raise into the sync path.
- An end-to-end-ish test: a sync action that performs an update produces a `changes.log` line with
  the old→new values (use a temp dir for `DATA_DIR`/path).
- Full backend suite green.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. Document in `docs/decisions.md`, add the env vars to `CLAUDE.md`'s env-var table + README, and
   mention the file in the README (where users can find it: `{DATA_DIR}/changes.log`).
3. **Do NOT commit or push** (per the session's batch flow) — leave in the working tree and report,
   unless instructed otherwise.

## Tooling
- Backend venv `backend/.venv/bin/python`. `bwrap: Can't mkdir .../private_data/...` → retry that
  command with `dangerouslyDisableSandbox: true`.
