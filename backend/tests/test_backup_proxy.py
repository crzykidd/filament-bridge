"""Tests for POST /api/backup/spoolman — Spoolman backup proxy."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import backup
from app.db import get_db


def _app_with_spoolman(spoolman_mock) -> FastAPI:
    app = FastAPI()
    app.include_router(backup.router, prefix="/api")
    # Provide a no-op db dependency (endpoint doesn't use it, but router is shared)
    engine_mock = MagicMock()
    app.dependency_overrides[get_db] = lambda: engine_mock
    app.state.spoolman = spoolman_mock
    return app


def test_backup_spoolman_success():
    """trigger_backup() returns a path → proxy returns success=True with detail."""
    sm = AsyncMock()
    sm.trigger_backup = AsyncMock(return_value={"path": "/spoolman/backups/2026-06-07.zip"})
    client = TestClient(_app_with_spoolman(sm))

    resp = client.post("/api/backup/spoolman")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "2026-06-07.zip" in body["detail"]
    sm.trigger_backup.assert_called_once()


def test_backup_spoolman_empty_body():
    """trigger_backup() returns {} → proxy still returns success=True with fallback detail."""
    sm = AsyncMock()
    sm.trigger_backup = AsyncMock(return_value={})
    client = TestClient(_app_with_spoolman(sm))

    resp = client.post("/api/backup/spoolman")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["detail"], str)


def test_backup_spoolman_http_status_error():
    """HTTP error from Spoolman → success=False, no 500."""
    sm = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.text = "Service Unavailable"
    sm.trigger_backup = AsyncMock(
        side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=mock_response)
    )
    client = TestClient(_app_with_spoolman(sm))

    resp = client.post("/api/backup/spoolman")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "503" in body["detail"]


def test_backup_spoolman_request_error():
    """Network-level error → success=False, no 500."""
    sm = AsyncMock()
    sm.trigger_backup = AsyncMock(
        side_effect=httpx.RequestError("Connection refused")
    )
    client = TestClient(_app_with_spoolman(sm))

    resp = client.post("/api/backup/spoolman")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert isinstance(body["detail"], str)
