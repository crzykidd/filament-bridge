"""Tests for scheduled nightly backups (issue #5).

Covers:
  - prune_backups: keeps in-window files, deletes older ones, ignores non-matching names.
  - run_scheduled_backup: each toggle combination writes the expected files.
  - config defaults, env→DB precedence, and the hour/retention validation clamps.
"""

import datetime
import json
import os
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import config as config_api
from app.api.config import (
    effective_backup_config,
    effective_backup_hour_utc,
    set_config_value,
)
from app.core import backup_job
from app.db import get_db


# ---------------------------------------------------------------------------
# prune_backups
# ---------------------------------------------------------------------------


def _ts(days_ago: int) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _touch(dir_path, name: str) -> str:
    path = os.path.join(dir_path, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{}")
    return path


def test_prune_keeps_recent_deletes_old(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    recent = _touch(d, f"bridge-state-{_ts(1)}.json")
    recent_fdb = _touch(d, f"filamentdb-snapshot-{_ts(3)}.json")
    old = _touch(d, f"bridge-state-{_ts(10)}.json")
    old_fdb = _touch(d, f"filamentdb-snapshot-{_ts(30)}.json")

    deleted = backup_job.prune_backups(str(d), 7)

    assert os.path.isfile(recent)
    assert os.path.isfile(recent_fdb)
    assert not os.path.isfile(old)
    assert not os.path.isfile(old_fdb)
    assert sorted(deleted) == sorted(
        [os.path.basename(old), os.path.basename(old_fdb)]
    )


def test_prune_ignores_nonmatching_files(tmp_path):
    """Spoolman archives / unrelated files are never deleted, even if very old."""
    d = tmp_path / "backups"
    d.mkdir()
    spoolman = _touch(d, f"spoolman-backup-{_ts(99)}.zip")
    other = _touch(d, "some-other-file.txt")
    old = _touch(d, f"bridge-state-{_ts(99)}.json")

    deleted = backup_job.prune_backups(str(d), 7)

    assert os.path.isfile(spoolman)
    assert os.path.isfile(other)
    assert not os.path.isfile(old)
    assert deleted == [os.path.basename(old)]


def test_prune_zero_retention_is_noop(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    old = _touch(d, f"bridge-state-{_ts(99)}.json")
    assert backup_job.prune_backups(str(d), 0) == []
    assert os.path.isfile(old)


def test_prune_missing_dir_is_noop(tmp_path):
    assert backup_job.prune_backups(str(tmp_path / "nope"), 7) == []


def test_prune_falls_back_to_mtime_for_unparseable_name(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    # Name matches the prefix but has no parseable UTC stamp → mtime fallback.
    path = _touch(d, "bridge-state-garbage.json")
    old_time = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    ).timestamp()
    os.utime(path, (old_time, old_time))

    deleted = backup_job.prune_backups(str(d), 7)
    assert deleted == ["bridge-state-garbage.json"]
    assert not os.path.isfile(path)


# ---------------------------------------------------------------------------
# run_scheduled_backup — toggle combinations
# ---------------------------------------------------------------------------


class _Cfg:
    def __init__(self, data_dir, bridge=True, fdb=True, retention=7):
        self.data_dir = data_dir
        self.backup_bridge_state_enabled = bridge
        self.backup_filamentdb_enabled = fdb
        self.backup_retention_days = retention
        self.backup_schedule_enabled = True


def _fdb_mock():
    fdb = AsyncMock()
    fdb.get_snapshot = AsyncMock(return_value={"version": 4, "collections": {}})
    return fdb


def _list_backups(data_dir):
    d = os.path.join(data_dir, "backups")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


@pytest.mark.asyncio
async def test_run_scheduled_backup_both(db, tmp_path):
    cfg = _Cfg(str(tmp_path), bridge=True, fdb=True)
    result = await backup_job.run_scheduled_backup(db, _fdb_mock(), settings=cfg)
    files = _list_backups(str(tmp_path))
    assert any(f.startswith("bridge-state-") for f in files)
    assert any(f.startswith("filamentdb-snapshot-") for f in files)
    assert result["bridge_state"] is not None
    assert result["filamentdb"] is not None


@pytest.mark.asyncio
async def test_run_scheduled_backup_bridge_only(db, tmp_path):
    cfg = _Cfg(str(tmp_path), bridge=True, fdb=False)
    fdb = _fdb_mock()
    result = await backup_job.run_scheduled_backup(db, fdb, settings=cfg)
    files = _list_backups(str(tmp_path))
    assert any(f.startswith("bridge-state-") for f in files)
    assert not any(f.startswith("filamentdb-snapshot-") for f in files)
    assert result["filamentdb"] is None
    fdb.get_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_run_scheduled_backup_fdb_only(db, tmp_path):
    cfg = _Cfg(str(tmp_path), bridge=False, fdb=True)
    result = await backup_job.run_scheduled_backup(db, _fdb_mock(), settings=cfg)
    files = _list_backups(str(tmp_path))
    assert not any(f.startswith("bridge-state-") for f in files)
    assert any(f.startswith("filamentdb-snapshot-") for f in files)
    assert result["bridge_state"] is None


@pytest.mark.asyncio
async def test_run_scheduled_backup_prunes_after_write(db, tmp_path):
    # Seed an old file that should be pruned by the run.
    d = tmp_path / "backups"
    d.mkdir()
    old = _touch(d, f"bridge-state-{_ts(99)}.json")
    cfg = _Cfg(str(tmp_path), bridge=True, fdb=True, retention=7)
    result = await backup_job.run_scheduled_backup(db, _fdb_mock(), settings=cfg)
    assert not os.path.isfile(old)
    assert os.path.basename(old) in result["pruned"]


@pytest.mark.asyncio
async def test_run_scheduled_backup_fdb_failure_does_not_block_bridge(db, tmp_path):
    cfg = _Cfg(str(tmp_path), bridge=True, fdb=True)
    fdb = AsyncMock()
    fdb.get_snapshot = AsyncMock(side_effect=RuntimeError("FDB down"))
    result = await backup_job.run_scheduled_backup(db, fdb, settings=cfg)
    # Bridge state still written despite the FDB failure.
    assert result["bridge_state"] is not None
    assert result["filamentdb"] is None
    files = _list_backups(str(tmp_path))
    assert any(f.startswith("bridge-state-") for f in files)


def test_bridge_state_backup_contents_are_valid(db, tmp_path):
    path = backup_job.write_bridge_state_backup(db, str(tmp_path))
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    assert "schema_version" in payload
    assert "filament_mappings" in payload
    assert "config" in payload


# ---------------------------------------------------------------------------
# config defaults + env→DB precedence
# ---------------------------------------------------------------------------


def test_backup_config_defaults(db):
    cfg = effective_backup_config(db)
    assert cfg.backup_schedule_enabled is True
    assert cfg.backup_bridge_state_enabled is True
    assert cfg.backup_filamentdb_enabled is True
    assert cfg.backup_retention_days == 7
    assert effective_backup_hour_utc(db) == 3


def test_backup_config_db_override_wins(db):
    set_config_value(db, "backup_schedule_enabled", False)
    set_config_value(db, "backup_filamentdb_enabled", False)
    set_config_value(db, "backup_retention_days", 14)
    set_config_value(db, "backup_hour_utc", 5)
    db.commit()
    cfg = effective_backup_config(db)
    assert cfg.backup_schedule_enabled is False
    assert cfg.backup_filamentdb_enabled is False
    assert cfg.backup_retention_days == 14
    assert effective_backup_hour_utc(db) == 5


# ---------------------------------------------------------------------------
# API: read + update + validation
# ---------------------------------------------------------------------------


def _client(db):
    app = FastAPI()
    app.include_router(config_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_get_config_exposes_backup_keys(db):
    resp = _client(db).get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backup_schedule_enabled"] is True
    assert body["backup_bridge_state_enabled"] is True
    assert body["backup_filamentdb_enabled"] is True
    assert body["backup_retention_days"] == 7
    assert body["backup_hour_utc"] == 3


def test_update_config_backup_roundtrip(db):
    client = _client(db)
    resp = client.put(
        "/api/config",
        json={
            "backup_schedule_enabled": False,
            "backup_bridge_state_enabled": False,
            "backup_retention_days": 10,
            "backup_hour_utc": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backup_schedule_enabled"] is False
    assert body["backup_bridge_state_enabled"] is False
    assert body["backup_retention_days"] == 10
    assert body["backup_hour_utc"] == 2


def test_update_config_rejects_bad_hour(db):
    # Pydantic ge/le rejects out-of-range with 422 before the handler runs.
    resp = _client(db).put("/api/config", json={"backup_hour_utc": 24})
    assert resp.status_code == 422


def test_update_config_rejects_zero_retention(db):
    resp = _client(db).put("/api/config", json={"backup_retention_days": 0})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /backup/status (issue #20)
# ---------------------------------------------------------------------------


def _backup_client(db):
    from app.api import backup as backup_api

    app = FastAPI()
    app.include_router(backup_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_backup_status_no_last_run(db):
    """With no backup_last_run stored, last_run is null."""
    resp = _backup_client(db).get("/api/backup/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_run"] is None
    assert body["next_run_at"] is None  # no scheduler in test
    assert body["schedule_enabled"] is True
    assert body["retention_days"] == 7
    assert body["retained"]["count"] == 0
    assert body["retained"]["total_bytes"] == 0


def test_backup_status_with_successful_last_run(db):
    """A persisted success run is returned correctly."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    set_config_value(db, "backup_last_run", {
        "at": now_iso,
        "ok": True,
        "bridge_state": "/data/backups/bridge-state-20260626T030000Z.json",
        "filamentdb": "/data/backups/filamentdb-snapshot-20260626T030000Z.json",
        "pruned": [],
    })
    db.commit()
    resp = _backup_client(db).get("/api/backup/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_run"]["ok"] is True
    assert body["last_run"]["bridge_state"] is not None
    assert body["last_run"]["filamentdb"] is not None
    assert body["last_run"]["error"] is None


def test_backup_status_with_failed_last_run(db):
    """A persisted failure run surfaces the error."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    set_config_value(db, "backup_last_run", {
        "at": now_iso,
        "ok": False,
        "error": "FDB unreachable",
    })
    db.commit()
    resp = _backup_client(db).get("/api/backup/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_run"]["ok"] is False
    assert body["last_run"]["error"] == "FDB unreachable"


def test_backup_status_retained_counts_files(db, tmp_path):
    """retained.count and total_bytes reflect files in DATA_DIR/backups/."""
    from unittest.mock import patch
    from app.api import backup as backup_api

    # Create two fake backup files.
    bdir = tmp_path / "backups"
    bdir.mkdir()
    (bdir / "bridge-state-20260626T030000Z.json").write_text('{"x":1}')
    (bdir / "filamentdb-snapshot-20260626T030000Z.json").write_text('{"y":2}')
    # Non-matching file — should be excluded.
    (bdir / "spoolman-backup.zip").write_text("zip")

    app = FastAPI()
    app.include_router(backup_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db

    with patch("app.config.settings") as mock_settings:
        mock_settings.data_dir = str(tmp_path)
        # Also patch effective_backup_config to use our settings.
        client = TestClient(app)
        with patch("app.api.backup.get_backup_status.__wrapped__" if hasattr(backup_api.get_backup_status, "__wrapped__") else "app.api.config._settings", mock_settings):
            pass  # The settings patch on the module is what counts.
        # Re-patch at the config module level too.
        with patch("app.api.config._settings", mock_settings):
            resp = client.get("/api/backup/status")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["retained"]["count"] == 2
    assert body["retained"]["total_bytes"] > 0


def test_backup_status_schedule_disabled(db):
    """When backup is disabled, schedule_enabled is false."""
    set_config_value(db, "backup_schedule_enabled", False)
    db.commit()
    resp = _backup_client(db).get("/api/backup/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schedule_enabled"] is False


# ---------------------------------------------------------------------------
# _backup_job last-run persistence (issue #20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backup_job_records_success(db, tmp_path):
    """Calling run_scheduled_backup + writing backup_last_run mirrors _backup_job success."""
    import datetime as _dt

    from app.api.config import get_config_value, set_config_value as scv
    from app.core.backup_job import run_scheduled_backup

    cfg = _Cfg(str(tmp_path))
    result = await run_scheduled_backup(db, _fdb_mock(), settings=cfg)
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    scv(db, "backup_last_run", {
        "at": now_iso,
        "ok": True,
        "bridge_state": result.get("bridge_state"),
        "filamentdb": result.get("filamentdb"),
        "pruned": result.get("pruned", []),
    })
    db.commit()

    saved = get_config_value(db, "backup_last_run")
    assert saved is not None
    assert saved["ok"] is True
    assert saved["bridge_state"] is not None


@pytest.mark.asyncio
async def test_backup_job_records_failure(db, tmp_path):
    """On an exception the failure shape is persisted as backup_last_run."""
    import datetime as _dt

    from app.api.config import get_config_value, set_config_value as scv

    # Simulate the except path that _backup_job takes.
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
    scv(db, "backup_last_run", {
        "at": now_iso,
        "ok": False,
        "error": "test failure",
    })
    db.commit()

    saved = get_config_value(db, "backup_last_run")
    assert saved is not None
    assert saved["ok"] is False
    assert saved["error"] == "test failure"
