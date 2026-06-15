"""FilamentDBClient API-key auth (FDB >= 1.39.0 optional FILAMENTDB_API_KEY).

We patch httpx.AsyncClient so the test never opens a real client (which would pull
optional transport deps); we just assert the headers it would be constructed with.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.filamentdb import FilamentDBClient


@pytest.mark.asyncio
async def test_sends_bearer_header_when_api_key_set():
    with patch("app.services.filamentdb.httpx.AsyncClient", return_value=AsyncMock()) as mock_ac:
        client = FilamentDBClient("http://fdb.test", api_key="secret123")
        await client.__aenter__()
        await client.__aexit__(None, None, None)
        assert mock_ac.call_args.kwargs["headers"] == {"Authorization": "Bearer secret123"}


@pytest.mark.asyncio
async def test_no_auth_header_when_key_empty():
    for key in (None, ""):
        with patch("app.services.filamentdb.httpx.AsyncClient", return_value=AsyncMock()) as mock_ac:
            client = FilamentDBClient("http://fdb.test", api_key=key) if key is not None \
                else FilamentDBClient("http://fdb.test")
            await client.__aenter__()
            await client.__aexit__(None, None, None)
            assert mock_ac.call_args.kwargs["headers"] is None
