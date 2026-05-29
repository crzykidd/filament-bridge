---
name: 2026-05-28-phase1-sqlite-persistence
status: completed
created: 2026-05-28
model: sonnet
completed: 2026-05-28
result: >
  All five SQLAlchemy models created (FilamentMapping, SpoolMapping, Conflict, SyncLog,
  Snapshot, BridgeConfig). Alembic initialized with env.py wired to app.db.Base and all
  model modules. Initial migration generated (9e504c864be4) covering all 6 tables.
  main.py lifespan updated to run migrations and seed BridgeConfig defaults on startup.
  Verified: sqlite3 shows all 6 tables, all 6 seed rows present, alembic current reports head.
  Sync SQLAlchemy decision recorded in docs/decisions.md.
---

# Task: Phase 1 — SQLite persistence layer

Add SQLAlchemy models, Alembic migrations, and a database session factory so that
Phase 2 (sync engine) and Phase 3 (wizard API) have a working persistence layer to
write to. No sync logic yet — just schema, seed defaults, and startup wiring.

## Before you start

- **Read `docs/prd.md`** — especially the architecture section and FR-8/FR-13/FR-17.
- **Read `CLAUDE.md`** — the models/ directory structure, tech stack, and env vars.
- **Read `docs/decisions.md`** — the Docker image choice and version file location.
- **Read `backend/app/config.py`** and **`backend/app/main.py`** to understand what
  already exists (Phase 0). Phase 1 adds DB wiring to the existing lifespan.
- Use `vexp run_pipeline` for code context, not grep/glob.

## Working tree check

Run `git status --porcelain` before editing. Cross-reference the files listed under
"What to do". If any are dirty, list them and ask. Surface unrelated dirty files once
as awareness; don't block.

## Design decision: sync SQLAlchemy (not async)

Use **synchronous** SQLAlchemy (`create_engine`, `Session`) rather than the async
variant (`create_async_engine`, `AsyncSession`). Rationale:

- SQLite read/write latency is microseconds — the HTTP calls to Spoolman and Filament DB
  are the only bottleneck worth async-ing.
- Sync SQLAlchemy + Alembic is straightforward. Async SQLAlchemy + Alembic requires a
  sync compatibility shim that adds complexity for zero practical gain here.
- FastAPI automatically runs sync `Depends` handlers in a threadpool, so sync DB sessions
  in route handlers are safe.

Record this in `docs/decisions.md`.

## What to do

### 1. `backend/requirements.txt` — add persistence deps

```
sqlalchemy>=2.0.0,<3.0.0
alembic>=1.13.0,<2.0.0
```

### 2. `backend/app/db.py` — engine, session factory, Base, dependency

```python
engine = create_engine(
    f"sqlite:///{settings.data_dir}/bridge.db",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### 3. `backend/app/models/` — five model files

Create `backend/app/models/__init__.py` (empty) plus the five files below. Use
`func.now()` for server-side datetime defaults. All datetimes are UTC.

**`backend/app/models/mapping.py`** — cross-reference records linking Spoolman ↔ Filament DB

- `FilamentMapping` table `filament_mappings`:
  - `id` Integer PK
  - `spoolman_filament_id` Integer UNIQUE NOT NULL (Spoolman integer ID)
  - `filamentdb_id` String(24) NOT NULL (Filament DB filament ObjectId)
  - `filamentdb_parent_id` String(24) NULLABLE (ObjectId of FDB parent filament, when this is a variant)
  - `created_at` DateTime NOT NULL default now
  - `updated_at` DateTime NOT NULL default now, onupdate now

- `SpoolMapping` table `spool_mappings`:
  - `id` Integer PK
  - `spoolman_spool_id` Integer UNIQUE NOT NULL
  - `filamentdb_filament_id` String(24) NOT NULL (FDB parent filament ObjectId)
  - `filamentdb_spool_id` String(24) NOT NULL (FDB spool subdocument ObjectId)
  - `filament_mapping_id` Integer FK → `filament_mappings.id` NULLABLE SET NULL on delete
  - `created_at` DateTime NOT NULL default now
  - `updated_at` DateTime NOT NULL default now, onupdate now

**`backend/app/models/conflict.py`** — conflict queue (never auto-resolved; survives restarts)

- `Conflict` table `conflicts`:
  - `id` Integer PK
  - `entity_type` String NOT NULL — "spool" | "filament"
  - `spoolman_id` Integer NULLABLE
  - `filamentdb_filament_id` String(24) NULLABLE
  - `filamentdb_spool_id` String(24) NULLABLE
  - `field_name` String NOT NULL
  - `spoolman_value` Text NULLABLE (JSON-encoded)
  - `filamentdb_value` Text NULLABLE (JSON-encoded)
  - `detected_at` DateTime NOT NULL default now
  - `resolved_at` DateTime NULLABLE
  - `resolution` String NULLABLE — "spoolman" | "filamentdb" | "manual"
  - `resolved_value` Text NULLABLE (JSON-encoded; the value written to both sides)

**`backend/app/models/sync_log.py`** — audit trail (FR-17; every sync action logged)

- `SyncLog` table `sync_log`:
  - `id` Integer PK
  - `cycle_id` String NOT NULL (UUID; groups all entries from one sync run)
  - `timestamp` DateTime NOT NULL default now
  - `direction` String NOT NULL — "spoolman_to_filamentdb" | "filamentdb_to_spoolman"
  - `action` String NOT NULL — "create" | "update" | "conflict" | "skip" | "error"
  - `entity_type` String NOT NULL — "spool" | "filament"
  - `spoolman_id` Integer NULLABLE
  - `filamentdb_filament_id` String(24) NULLABLE
  - `filamentdb_spool_id` String(24) NULLABLE
  - `field_name` String NULLABLE
  - `old_value` Text NULLABLE (JSON-encoded)
  - `new_value` Text NULLABLE (JSON-encoded)
  - `error_message` Text NULLABLE

**`backend/app/models/snapshot.py`** — last-known state of each entity (basis for diffing)

- `Snapshot` table `snapshots`:
  - `id` Integer PK
  - `source` String NOT NULL — "spoolman" | "filamentdb"
  - `entity_type` String NOT NULL — "spool" | "filament"
  - `entity_id` String NOT NULL (Spoolman int or FDB ObjectId, always stored as string)
  - `data` Text NOT NULL (full entity JSON blob)
  - `captured_at` DateTime NOT NULL default now
  - UniqueConstraint on `(source, entity_type, entity_id)`

**`backend/app/models/config.py`** — persisted runtime config (source-of-truth choices, auto-sync flag)

These are the settings the user controls via the UI — distinct from the startup env vars
in `app/config.py` which control connection URLs and intervals.

- `BridgeConfig` table `bridge_config`:
  - `key` String PK
  - `value` Text NOT NULL (JSON-encoded)
  - `updated_at` DateTime NOT NULL default now, onupdate now

Seed these default rows on first startup (use `INSERT OR IGNORE`):

| key | default value |
|-----|---------------|
| `weight_source_of_truth` | `"spoolman"` |
| `material_properties_source_of_truth` | `"filamentdb"` |
| `new_spool_source_of_truth` | `"spoolman"` |
| `auto_sync_enabled` | `false` |
| `sync_weight_threshold_grams` | `2.0` |
| `wizard_completed` | `false` |

### 4. Alembic setup

Initialize Alembic from the `backend/` directory:

```bash
cd backend && alembic init alembic
```

Then configure it:

- `alembic.ini`: set `script_location = alembic` and `sqlalchemy.url = sqlite:///./bridge.db`
  (a relative path for local use; the app overrides this at runtime via `env.py`).
- `alembic/env.py`: import `Base` from `app.db` and all model modules so autogenerate
  sees every table. Override `sqlalchemy.url` from `settings.data_dir` when running
  inside the app. Example env.py pattern:

```python
from app.config import settings
from app.db import Base
import app.models.mapping      # noqa: F401
import app.models.conflict     # noqa: F401
import app.models.sync_log     # noqa: F401
import app.models.snapshot     # noqa: F401
import app.models.config       # noqa: F401

config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.data_dir}/bridge.db")
target_metadata = Base.metadata
```

Generate the initial migration:

```bash
cd backend && alembic revision --autogenerate -m "initial schema"
```

Review the generated file in `alembic/versions/` — confirm all five tables appear.

### 5. `backend/app/main.py` — wire DB into lifespan

In the lifespan context, before starting the scheduler:
1. Run `alembic upgrade head` (or `Base.metadata.create_all(engine)` as a fast fallback
   during early development). For production correctness, use Alembic.
2. Seed default `BridgeConfig` rows (`INSERT OR IGNORE`).
3. Log the DB path and migration version.

Recommended approach — run Alembic programmatically:

```python
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

def _run_migrations() -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.data_dir}/bridge.db")
    alembic_command.upgrade(cfg, "head")
```

### 6. Verify it works

```bash
cd backend
DATA_DIR=/tmp/bridge-test \
FILAMENTDB_URL=http://localhost:3000 \
SPOOLMAN_URL=http://localhost:7912 \
.venv/bin/uvicorn app.main:app --port 8090
```

Then in another shell:
```bash
sqlite3 /tmp/bridge-test/bridge.db ".tables"
# expected: bridge_config  conflicts  filament_mappings  snapshots  spool_mappings  sync_log
sqlite3 /tmp/bridge-test/bridge.db "SELECT key, value FROM bridge_config;"
# expected: the 6 seed rows
```

Also verify `alembic current` reports `head`:
```bash
cd backend && DATA_DIR=/tmp/bridge-test \
  FILAMENTDB_URL=http://localhost:3000 SPOOLMAN_URL=http://localhost:7912 \
  .venv/bin/alembic current
```

## Conventions to honor

- Sync SQLAlchemy (see design decision above — record it in `docs/decisions.md`).
- `func.now()` for DB-side defaults, not Python `datetime.utcnow()`.
- `check_same_thread=False` on the SQLite engine (FastAPI uses multiple threads).
- All datetimes stored as UTC; no timezone info in the column (SQLite has no native tz type).
- Data dir comes from `settings.data_dir`; ensure the directory exists before opening the DB.
- No raw `json.loads`/`json.dumps` calls scattered in routes — that's Phase 2's concern;
  here just define the columns as `Text` and note they store JSON.
- Keep models thin — no business logic, no sync rules, just columns + relationships.
- No tests required yet; the manual sqlite3 check above is sufficient for Phase 1.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/`.
3. Record the sync/async SQLAlchemy decision in `docs/decisions.md`.
4. Propose ONE commit:
   - `feat: Phase 1 — SQLite persistence layer, Alembic migrations, config seed`
   - Files: `requirements.txt`, `app/db.py`, `app/models/*`, `alembic/`, `alembic.ini`,
     `app/main.py` (lifespan update), `docs/decisions.md`, prompt move.
   - Ask `commit these as "<message>"? (y/n)` before staging.
   - Stage specific paths only; commit on `dev`; no push.
