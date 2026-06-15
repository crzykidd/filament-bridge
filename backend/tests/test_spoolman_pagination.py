"""Tests for SpoolmanClient pagination (fix #4 — offset pagination for large libraries)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.spoolman import SpoolmanClient


def _make_response(data: list[dict]) -> MagicMock:
    """Return a mock httpx response that yields *data* as JSON."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=data)
    return resp


def _spool_row(i: int) -> dict:
    return {
        "id": i,
        "filament": {"id": i, "name": "PLA", "vendor": {"id": 1, "name": "ACME"}},
        "archived": False,
    }


def _filament_row(i: int) -> dict:
    return {"id": i, "name": f"PLA {i}"}


@pytest.mark.asyncio
async def test_get_spools_paginates_across_two_pages():
    """get_spools paginates the active endpoint, then fetches the archived endpoint."""
    page1 = [_spool_row(i) for i in range(1000)]
    page2 = [_spool_row(i) for i in range(1000, 1005)]

    client = SpoolmanClient("http://spoolman.test")
    client._client = AsyncMock()

    # active page1, active page2, then the (empty) archived fetch.
    client._client.get = AsyncMock(
        side_effect=[_make_response(page1), _make_response(page2), _make_response([])]
    )

    spools = await client.get_spools()

    assert len(spools) == 1005
    calls = client._client.get.call_args_list
    assert len(calls) == 3  # 2 active pages + 1 archived fetch
    assert calls[0].kwargs["params"]["offset"] == 0
    assert "archived" not in calls[0].kwargs["params"]
    assert calls[1].kwargs["params"]["offset"] == 1000
    assert calls[2].kwargs["params"].get("archived") == "true"


@pytest.mark.asyncio
async def test_get_spools_makes_one_request_per_endpoint():
    """A single-page library still costs one active request + one archived request."""
    page1 = [_spool_row(i) for i in range(5)]

    client = SpoolmanClient("http://spoolman.test")
    client._client = AsyncMock()
    client._client.get = AsyncMock(side_effect=[_make_response(page1), _make_response([])])

    spools = await client.get_spools()

    assert len(spools) == 5
    assert client._client.get.call_count == 2  # active + archived


@pytest.mark.asyncio
async def test_get_spools_merges_active_and_archived():
    """get_spools fetches BOTH endpoints and merges — archived spools are included."""
    active = [_spool_row(1), _spool_row(2)]
    archived = [
        {**_spool_row(3), "archived": True},
        {**_spool_row(4), "archived": True},
    ]

    client = SpoolmanClient("http://spoolman.test")
    client._client = AsyncMock()
    client._client.get = AsyncMock(
        side_effect=[_make_response(active), _make_response(archived)]
    )

    spools = await client.get_spools()
    by_id = {s.id: s for s in spools}

    assert set(by_id) == {1, 2, 3, 4}
    assert by_id[3].archived is True and by_id[4].archived is True
    calls = client._client.get.call_args_list
    assert "archived" not in calls[0].kwargs["params"]
    assert calls[1].kwargs["params"].get("archived") == "true"


@pytest.mark.asyncio
async def test_get_filaments_paginates_across_two_pages():
    """get_filaments also uses offset pagination for large libraries."""
    page1 = [_filament_row(i) for i in range(1000)]
    page2 = [_filament_row(i) for i in range(1000, 1005)]

    client = SpoolmanClient("http://spoolman.test")
    client._client = AsyncMock()
    client._client.get = AsyncMock(
        side_effect=[_make_response(page1), _make_response(page2)]
    )

    filaments = await client.get_filaments()

    assert len(filaments) == 1005
    calls = client._client.get.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["params"]["offset"] == 0
    assert calls[1].kwargs["params"]["offset"] == 1000
