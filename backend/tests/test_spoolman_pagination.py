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
    """get_spools fetches page 2 when page 1 is exactly PAGE_SIZE records."""
    page1 = [_spool_row(i) for i in range(1000)]
    page2 = [_spool_row(i) for i in range(1000, 1005)]

    client = SpoolmanClient("http://spoolman.test")
    client._client = AsyncMock()

    # Return page1 on first call, page2 on second call.
    client._client.get = AsyncMock(
        side_effect=[_make_response(page1), _make_response(page2)]
    )

    spools = await client.get_spools()

    assert len(spools) == 1005
    # Verify offset pagination was used correctly.
    calls = client._client.get.call_args_list
    assert len(calls) == 2
    # The call is get(path, params=...)
    assert calls[0].kwargs["params"]["offset"] == 0
    assert calls[1].kwargs["params"]["offset"] == 1000


@pytest.mark.asyncio
async def test_get_spools_single_page_no_second_request():
    """get_spools makes exactly one request when the response is less than PAGE_SIZE."""
    page1 = [_spool_row(i) for i in range(5)]

    client = SpoolmanClient("http://spoolman.test")
    client._client = AsyncMock()
    client._client.get = AsyncMock(return_value=_make_response(page1))

    spools = await client.get_spools()

    assert len(spools) == 5
    assert client._client.get.call_count == 1


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
