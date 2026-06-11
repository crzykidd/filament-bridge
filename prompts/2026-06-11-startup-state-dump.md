---
name: 2026-06-11-startup-state-dump
status: pending
created: 2026-06-11
model: sonnet
completed:
result:
---

# Task: Debug startup state dump — write a txt snapshot of Spoolman + Filament DB records at boot

User request 2026-06-11: when heavy-testing against a live environment, knowing the exact
upstream state at boot makes it possible to track what changed against the (planned)
`changes.log`. Gated by a **`.env` debug setting** so normal installs never write it.

## Design

1. **Env var, not runtime config:** add `DEBUG_STARTUP_DUMP` (bool, default `false`) to
   `backend/app/config.py` `Settings`. This is deliberately env-level (boot-time behavior),
   separate from the runtime `debug_mode` BridgeConfig flag that gates the reset endpoints.
2. **When:** in `main.py`'s lifespan, after both HTTP clients are open (right around
   `ensure_extra_fields`). Run it as a **background task** (`asyncio.create_task`) so a
   large library or a slow upstream never delays startup; hold a reference to the task and
   await/cancel it cleanly on shutdown if still running.
3. **Where:** `{DATA_DIR}/state-dumps/startup-state-<UTC ISO basic ts>.txt`
   (e.g. `startup-state-20260611T154500Z.txt`). Create the dir if missing.
   **Retention:** after writing, delete the oldest files beyond the newest **10** dumps
   (simple sorted-by-name prune; document the cap in the file header).
4. **Format — human-readable text, one record per line**, stable field order so two dumps
   diff cleanly. Suggested shape:

   ```
   # filament-bridge startup state dump
   # written: 2026-06-11T15:45:00Z   bridge: 0.1.0   spoolman: 0.22.1   filamentdb: 1.37.0
   # retention: newest 10 dumps kept in this directory

   == SPOOLMAN FILAMENTS (175) ==
   filament #12 | Hatchbox | PLA | "Light Blue" | color=ADD8E6 | density=1.24 | dia=1.75 | spool_weight=200 | weight=1000 | price=24.99 | extra: filamentdb_id=665f… opentag_uuid=ccf3…
   ...
   == SPOOLMAN SPOOLS (223) ==
   spool #42 | filament #12 "Light Blue" | remaining=916.9 | used=83.1 | location=Bin 3 | lot= | archived=false | extra: filamentdb_spool_id=665f… filamentdb_parent_id=…
   ...
   == FILAMENT DB FILAMENTS (140) ==
   filament 665f0c… | "Hatchbox PLA Light Blue" | vendor=Hatchbox | type=PLA | color=#ADD8E6 | density=1.24 | spoolWeight=200 | netFilamentWeight=1000 | cost=24.99 | parentId=664a… | optTags=[17]
   ...
   == FILAMENT DB SPOOLS (210) ==
   spool 665f0d… | filament 665f0c… "Hatchbox PLA Light Blue" | totalWeight=1116.9 | label=42 | retired=false
   ```

   - Use the LIST views only (`get_filaments`/`get_spools` both sides) — do NOT fetch
     per-record detail (that would hammer FDB at boot).
   - Decode Spoolman extra values via `decode_extra_value`; only print the bridge's
     cross-ref/OpenTag extras (configured key names), skip empties. `None` → omit or `—`,
     keep lines compact.
   - Sort each section by id for stable diffs.
5. **Robustness:** the dump must NEVER break or fail startup — wrap the whole task in
   try/except, log a warning on any fetch/write error, write nothing partial-garbage
   (build the text in memory, write once). Respect that the entrypoint already chowns
   DATA_DIR.
6. **Module:** `backend/app/core/state_dump.py` with a pure-ish
   `format_state_dump(sm_filaments, sm_spools, fdb_filaments, versions, now) -> str` (unit
   testable, clock injected) and an async `write_startup_dump(spoolman, filamentdb,
   data_dir, settings)` orchestrator + `prune_dumps(dir, keep=10)`.

## Docs

- Add `DEBUG_STARTUP_DUMP` to the env tables in `README.md`, `docs/configuration.md`
  ("Build / logging / misc" section), and `CLAUDE.md`.
- One-line mention in `docs/configuration.md` of where the files land and the keep-10 cap.

## Tests

- `format_state_dump`: stable ordering, section counts in headers, extras decoded,
  None handling, injected clock.
- `prune_dumps`: keeps newest 10, deletes older, tolerates non-dump files in the dir.
- `write_startup_dump`: with mocked clients writes the file to a tmp DATA_DIR; a client
  that raises → no file, no exception propagated.
- Gate: settings flag false → lifespan schedules nothing (test at whatever seam is
  practical — e.g. assert `write_startup_dump` not called via monkeypatch).
- Full backend suite green.

## Before you start

- Read `backend/app/main.py` (lifespan), `backend/app/config.py`, `services/spoolman.py`,
  `services/filamentdb.py`, `schemas/` for field names, and `core/opentag_cache.py` for an
  existing example of DATA_DIR file handling.

## Working tree check

Run `git status --porcelain` first. Tree should be clean apart from unrelated untracked
dotfiles in the repo root. If main.py/config.py are dirty, stop and report.

## When done

1. Update frontmatter; `git mv` to `prompts/done/`.
2. `docs/decisions.md` entry (env-level vs runtime gating, format, retention).
3. Propose ONE commit (`feat:` prefix, no Co-authored-by), on `dev`.
