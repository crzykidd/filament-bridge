# Backups

filament-bridge keeps its own state (mappings, runtime config, open conflicts) in a
SQLite database under `DATA_DIR`. It is **not** a copy of Filament DB or Spoolman — those
systems own their data. This page covers every backup path the bridge offers: manual
exports, the one-click upstream proxies, and the nightly scheduled job.

> The bridge's own `bridge.db` SQLite file still relies on a **host-volume backup**.
> Exporting the bridge state (below) protects your mappings and config, but it does not
> copy the database file itself. Back up the `DATA_DIR` volume the way you back up any
> other Docker volume.

## Manual backup & restore (bridge state)

In **Settings → Backup**:

- **Download backup** — `GET /api/backup/export` returns a versioned JSON dump of the
  bridge's state: all spool/filament mappings (with cross-reference IDs), runtime config,
  and unresolved conflicts. Save the file somewhere safe.
- **Import backup** — `POST /api/backup/import` restores a previously downloaded dump.
  Import is idempotent (re-importing the same file makes no further changes) and validated
  against the schema version.

This is the right tool for migrating the bridge to a new host or recovering from a
corrupted SQLite database.

### What the backup deliberately excludes

Auth secrets and internal state are **not** included in any backup export (manual or
scheduled), and are silently ignored if present in an imported file:

| Excluded key | Reason |
|---|---|
| `auth_secret` | Cookie-signing key — exporting it would let anyone with the file forge session cookies |
| `admin_password_hash` | bcrypt password hash — importing it would overwrite the target instance's password |
| `api_token` | Bridge REST API token — kept per-instance |
| `labelforge_token` | LabelForge bearer token — external-service credential, kept per-instance |
| `backup_last_run` / `wizard_last_run` | Per-instance run summaries — meaningless on a different instance |

A restored backup therefore keeps the **target instance's own credentials** intact. If
you are migrating to a new host and want to carry over the admin password and API token,
reset them via Settings after the restore.

## Upstream backup proxies (one-click)

These let you trigger an upstream backup without leaving the bridge UI. Each is guarded by
a pre-write safety dialog.

- **Spoolman** — `POST /api/backup/spoolman` proxies to Spoolman's own
  `POST /api/v1/backup`. Spoolman writes the archive into **its own** data volume; the
  bridge never receives or stores the file (and therefore cannot prune it).
- **Filament DB** — `POST /api/backup/filamentdb` fetches Filament DB's full
  `GET /api/snapshot` (filaments, locations, print history, catalogs, tombstones) and
  writes it to `DATA_DIR/backups/filamentdb-snapshot-<UTC timestamp>.json`. Unlike
  Spoolman, FDB hands the snapshot to the caller, so the bridge stores it in its own
  volume.

## Scheduled nightly backups

A built-in job runs **nightly** and writes backups into `DATA_DIR/backups/`, then prunes
old files. It is **on by default** — once the bridge is deployed, backups happen
automatically without a cron host or manual clicks.

### What it backs up

Two independent toggles, **both ON by default**:

| Toggle | Produces | Contents |
|---|---|---|
| **Bridge state** | `bridge-state-<UTC ts>.json` | The same payload as `GET /api/backup/export` (mappings, config, open conflicts) |
| **Filament DB snapshot** | `filamentdb-snapshot-<UTC ts>.json` | The same `GET /api/snapshot` fetch used by the manual FDB backup |

### Why Spoolman is excluded

The scheduled job deliberately does **not** trigger Spoolman's server-side backup.
Spoolman writes its archive into its own volume, and the bridge has no way to prune it —
scheduling it would leak storage with no retention control. Use the manual
**Settings → Backup → Spoolman** button when you want a Spoolman archive.

### Where files land

All scheduled backups go to `DATA_DIR/backups/` (the same directory the manual FDB
backup already uses). The bridge's data volume must be mounted for the files to survive a
container restart.

### Schedule and retention

- **Schedule:** nightly at a configurable UTC hour (default `03:00`, minute 0).
- **Retention:** configurable, default **7 days**. Only files matching the two prefixes
  above (`bridge-state-` / `filamentdb-snapshot-`) are eligible for deletion. Spoolman
  archives and any unrelated files in the directory are never touched. File age is taken
  from the UTC timestamp embedded in the filename, falling back to the file mtime if the
  stamp can't be parsed. A prune pass also runs once at startup, so stale files clear even
  before the nightly hour is reached.

### Settings

In **Settings → Scheduled backups**:

- **Enable scheduled backups** — the master switch. When off, the nightly job is a no-op.
- **Back up bridge state** / **Back up Filament DB snapshot** — the two sub-toggles
  (greyed out while the master switch is off).
- **Retention (days)** — minimum 1.
- **Run at (UTC hour)** — 0–23.

Changes take effect immediately (the cron is rescheduled on save without a restart).

### Environment variables ↔ Settings

Env vars are the **start-up fallback**; the matching runtime setting wins when set (same
precedence as `SYNC_INTERVAL_SECONDS`). No restart is needed to change a runtime setting.

| Env var | Setting | Default | Meaning |
|---|---|---|---|
| `BACKUP_SCHEDULE_ENABLED` | Enable scheduled backups | `true` | Master switch for the nightly job |
| `BACKUP_BRIDGE_STATE_ENABLED` | Back up bridge state | `true` | Write the bridge-state export |
| `BACKUP_FILAMENTDB_ENABLED` | Back up Filament DB snapshot | `true` | Write the FDB snapshot |
| `BACKUP_RETENTION_DAYS` | Retention (days) | `7` | Delete bridge-written backups older than this |
| `BACKUP_HOUR_UTC` | Run at (UTC hour) | `3` | Hour of day (UTC, 0–23) the job fires at minute 0 |

## Backup status (observability)

The bridge surfaces backup status in two places so you can confirm the schedule is running:

### Dashboard

A compact **Last backup / Next backup** row appears in the sync timing card on the
Dashboard. It shows:

- **Last backup** — local timestamp and a green tick (success) or a red warning (failure
  with the error message in the tooltip).
- **Next backup** — the scheduler's next fire time (from APScheduler) in your local
  timezone, or "Disabled" when the master switch is off.

### Settings → Scheduled backups

A status block below the schedule controls shows the full last-run detail:

| Row | Content |
|---|---|
| Last backup | Timestamp + artifact labels ("bridge-state", "filamentdb") on success, or the failure reason. "Never run" when no scheduled run has completed yet. |
| Next backup | Scheduler's next fire time, or "Disabled". |
| Retained files | Count and total size of retained backup files in `DATA_DIR/backups/`, plus the active retention window. |

The **Run at (UTC hour)** selector now annotates the UTC hour with its local equivalent
(e.g. "03:00 UTC ≈ 22:00 local") so you can tell at a glance when the job fires in your
timezone.

### API

`GET /api/backup/status` returns the status payload:

```json
{
  "last_run": {
    "at": "2026-06-26T03:00:00+00:00",
    "ok": true,
    "bridge_state": "/data/backups/bridge-state-20260626T030000Z.json",
    "filamentdb": "/data/backups/filamentdb-snapshot-20260626T030000Z.json",
    "pruned": []
  },
  "next_run_at": "2026-06-27T03:00:00+00:00",
  "schedule_enabled": true,
  "retention_days": 7,
  "retained": {
    "count": 4,
    "total_bytes": 102400
  }
}
```

`last_run` is `null` until the first scheduled run completes (or fails). On failure,
`ok` is `false` and `error` contains the exception message; the artifact paths are absent.

## Restoring

- **Bridge state** — use **Settings → Backup → Import backup** with a `bridge-state-*.json`
  file (or any exported bridge backup).
- **Filament DB snapshot** — restore a `filamentdb-snapshot-*.json` through Filament DB's
  own snapshot/restore tooling; the bridge only stores the file, it does not restore it.
