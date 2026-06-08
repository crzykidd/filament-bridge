"""Tests for POST /api/backup/filamentdb — Filament DB snapshot download + persist."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import backup
from app.db import get_db


def _app_with_fdb(fdb_mock, data_dir: str) -> FastAPI:
    app = FastAPI()
    app.include_router(backup.router, prefix="/api")
    # No-op db dependency (not used by this endpoint)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.state.filamentdb = fdb_mock
    # Patch settings.data_dir to use the provided temp dir
    import app.config as config_module
    config_module.settings.data_dir = data_dir
    return app


def test_backup_filamentdb_success(tmp_path):
    """get_snapshot() succeeds → file written, success=True, path in detail."""
    snapshot = {"version": 4, "createdAt": "2026-06-08T00:00:00Z", "collections": {}}
    fdb = AsyncMock()
    fdb.get_snapshot = AsyncMock(return_value=snapshot)

    client = TestClient(_app_with_fdb(fdb, str(tmp_path)))
    resp = client.post("/api/backup/filamentdb")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    # The detail should be a path under tmp_path/backups/
    saved_path = body["detail"]
    assert "filamentdb-snapshot-" in saved_path
    assert saved_path.endswith(".json")
    assert os.path.isfile(saved_path)
    # File should contain the snapshot JSON
    with open(saved_path) as fh:
        written = json.load(fh)
    assert written["version"] == 4
    fdb.get_snapshot.assert_called_once()


def test_backup_filamentdb_creates_backups_dir(tmp_path):
    """Backups subdir is created automatically when it doesn't exist."""
    fdb = AsyncMock()
    fdb.get_snapshot = AsyncMock(return_value={"version": 4})
    # Ensure backups dir does not exist yet
    backup_dir = tmp_path / "backups"
    assert not backup_dir.exists()

    client = TestClient(_app_with_fdb(fdb, str(tmp_path)))
    resp = client.post("/api/backup/filamentdb")

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert backup_dir.is_dir()


def test_backup_filamentdb_http_status_error(tmp_path):
    """HTTP error from FDB → success=False, no 500."""
    fdb = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 502
    mock_response.text = "Bad Gateway"
    fdb.get_snapshot = AsyncMock(
        side_effect=httpx.HTTPStatusError("502", request=MagicMock(), response=mock_response)
    )

    client = TestClient(_app_with_fdb(fdb, str(tmp_path)))
    resp = client.post("/api/backup/filamentdb")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "502" in body["detail"]


def test_backup_filamentdb_request_error(tmp_path):
    """Network-level error → success=False, no 500."""
    fdb = AsyncMock()
    fdb.get_snapshot = AsyncMock(
        side_effect=httpx.RequestError("Connection refused")
    )

    client = TestClient(_app_with_fdb(fdb, str(tmp_path)))
    resp = client.post("/api/backup/filamentdb")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert isinstance(body["detail"], str)


def test_backup_filamentdb_io_error(tmp_path):
    """File-write error → success=False, no 500."""
    fdb = AsyncMock()
    fdb.get_snapshot = AsyncMock(return_value={"version": 4})

    client = TestClient(_app_with_fdb(fdb, str(tmp_path)))

    with patch("builtins.open", side_effect=OSError("Permission denied")):
        resp = client.post("/api/backup/filamentdb")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert isinstance(body["detail"], str)
