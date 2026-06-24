"""Tests for the mobile updates & labels phase-3 LabelForge printing.

Covers:
  * services/labelforge.LabelForgeClient: print success, 4xx surfaces detail,
    409 media-mismatch flag, network error → LabelForgeError (no bare 500).
  * api/labels: the 403 feature gate, "not configured" 400, the field catalog +
    CSV selection (only listed fields sent), qr_url from bridge_public_url vs
    request-derived, the 409 media-mismatch surface, printer-status proxy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import labels as labels_router
from app.api.config import set_config_value
from app.db import Base, get_db
from app.models.config import seed_defaults
from app.models.mapping import SpoolMapping
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor
from app.schemas.filamentdb import FDBFilamentDetail
from app.services.labelforge import LabelForgeClient, LabelForgeError


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    session.commit()
    return session


def _sm_spool():
    return SpoolmanSpool(
        id=42,
        filament=SpoolmanFilament(
            id=10, name="Galaxy Black", material="PLA",
            vendor=SpoolmanVendor(id=2, name="ELEGOO"), color_hex="111111",
        ),
        remaining_weight=800.0, archived=False, location="Shelf A",
    )


def _fdb_detail():
    return FDBFilamentDetail.model_validate({
        "_id": "fil-1", "name": "PLA", "spoolWeight": 200.0, "colorName": "Galaxy Black",
        "color": "#111111", "type": "PLA", "_inherited": [],
        "spools": [{"_id": "spool-1", "totalWeight": 1000.0, "retired": False}],
    })


def _fake_spoolman():
    client = AsyncMock()
    client.get_spool = AsyncMock(return_value=_sm_spool())
    return client


def _fake_filamentdb():
    client = AsyncMock()
    client.get_filament = AsyncMock(return_value=_fdb_detail())
    return client


def _client(db, *, enabled=True, configure=True) -> TestClient:
    if enabled:
        set_config_value(db, "mobile_labels_enabled", True)
    if configure:
        set_config_value(db, "labelforge_url", "http://labelforge.test")
        set_config_value(db, "labelforge_template", "spool")
        set_config_value(db, "labelforge_token", "tok")
        set_config_value(db, "labelforge_fields", "brand,color,number,qr_url")
    db.commit()

    app = FastAPI()
    app.include_router(labels_router.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = _fake_spoolman()
    app.state.filamentdb = _fake_filamentdb()
    return TestClient(app)


def _mock_lfc(monkeypatch, *, print_return=None, print_exc=None, status_return=None,
              status_exc=None):
    """Patch LabelForgeClient used by api/labels with a recording mock.

    Returns the inner mock so tests can assert on print_template call args.
    """
    inner = MagicMock()
    inner.print_template = AsyncMock(
        return_value=print_return or {"job_id": 7, "status": "ok"},
        side_effect=print_exc,
    )
    inner.printer_status = AsyncMock(
        return_value=status_return or {"ready": True, "model": "QL-800"},
        side_effect=status_exc,
    )

    class _FakeCM:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return inner

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(labels_router, "LabelForgeClient", _FakeCM)
    return inner


# ===========================================================================
# services/labelforge — mocked httpx transport
# ===========================================================================


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_client_print_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/print/spool"
        assert request.headers["Authorization"] == "Bearer tok"
        body = request.read().decode()
        assert "brand" in body
        return httpx.Response(200, json={"job_id": 3, "status": "queued"})

    client = LabelForgeClient("http://lf.test", "tok")
    client._client = httpx.AsyncClient(
        base_url="http://lf.test",
        transport=_transport(handler),
        headers={"Authorization": "Bearer tok"},
    )
    result = await client.print_template("spool", {"brand": "Prusa"})
    assert result == {"job_id": 3, "status": "queued"}
    await client._client.aclose()


@pytest.mark.asyncio
async def test_client_print_override_param():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["override"] = request.url.params.get("override")
        return httpx.Response(200, json={"job_id": 1})

    client = LabelForgeClient("http://lf.test", "tok")
    client._client = httpx.AsyncClient(
        base_url="http://lf.test", transport=_transport(handler)
    )
    await client.print_template("spool", {}, override=True)
    assert seen["override"] == "true"
    await client._client.aclose()


@pytest.mark.asyncio
async def test_client_print_400_surfaces_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Missing required field: 'brand'"})

    client = LabelForgeClient("http://lf.test", "tok")
    client._client = httpx.AsyncClient(
        base_url="http://lf.test", transport=_transport(handler)
    )
    with pytest.raises(LabelForgeError) as exc:
        await client.print_template("spool", {})
    assert exc.value.status_code == 400
    assert "Missing required field" in exc.value.message
    assert not exc.value.is_media_mismatch
    await client._client.aclose()


@pytest.mark.asyncio
async def test_client_print_409_media_mismatch_flag():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": {
                "error": "media_mismatch", "expected": "62", "loaded": "29",
                "override_allowed": True, "message": "Printer has 29 loaded...",
            }},
        )

    client = LabelForgeClient("http://lf.test", "tok")
    client._client = httpx.AsyncClient(
        base_url="http://lf.test", transport=_transport(handler)
    )
    with pytest.raises(LabelForgeError) as exc:
        await client.print_template("spool", {})
    assert exc.value.is_media_mismatch
    assert "29 loaded" in exc.value.message
    await client._client.aclose()


@pytest.mark.asyncio
async def test_client_network_error_raises_labelforge_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = LabelForgeClient("http://lf.test", "tok")
    client._client = httpx.AsyncClient(
        base_url="http://lf.test", transport=_transport(handler)
    )
    with pytest.raises(LabelForgeError) as exc:
        await client.print_template("spool", {})
    assert exc.value.status_code is None
    assert "Could not reach LabelForge" in exc.value.message
    await client._client.aclose()


@pytest.mark.asyncio
async def test_client_printer_status_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/printer/status"
        return httpx.Response(200, json={"ready": True, "model": "QL-800"})

    client = LabelForgeClient("http://lf.test", "tok")
    client._client = httpx.AsyncClient(
        base_url="http://lf.test", transport=_transport(handler)
    )
    status = await client.printer_status()
    assert status["ready"] is True
    await client._client.aclose()


# ===========================================================================
# api/labels — feature gate + not-configured
# ===========================================================================


def test_print_403_when_feature_disabled(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    client = _client(db, enabled=False)
    _mock_lfc(monkeypatch)
    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "mobile_labels_disabled"


def test_print_400_when_not_configured(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    client = _client(db, configure=False)
    _mock_lfc(monkeypatch)
    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "labelforge_not_configured"


def test_print_404_when_unmapped(monkeypatch):
    db = _make_db()  # no mapping
    client = _client(db)
    _mock_lfc(monkeypatch)
    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "spool_not_mapped"


# ===========================================================================
# api/labels — field catalog + CSV selection
# ===========================================================================


def test_print_sends_only_csv_fields_with_request_derived_qr(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    # CSV omits material + color_hex → only brand,color,number,qr_url sent.
    client = _client(db)
    inner = _mock_lfc(monkeypatch)

    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 200
    assert r.json() == {"job_id": 7, "status": "ok"}

    name, fields, media, *_ = inner.print_template.await_args.args
    # template name + the selected fields only
    assert name == "spool"
    assert set(fields.keys()) == {"brand", "color", "number", "qr_url"}
    assert fields["brand"] == "ELEGOO"
    assert fields["color"] == "Galaxy Black"
    assert fields["number"] == "42"  # Spoolman spool id, stringified
    # qr_url request-derived (no bridge_public_url set) → host from testclient.
    assert fields["qr_url"].endswith("/r/fil-1/spool-1")
    assert "://" in fields["qr_url"]
    # No media configured → None.
    assert media is None


def test_print_qr_url_uses_bridge_public_url_when_set(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    set_config_value(db, "bridge_public_url", "https://bridge.example.com/")  # trailing slash stripped
    set_config_value(db, "labelforge_label_media", "62")
    client = _client(db)
    inner = _mock_lfc(monkeypatch)

    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 200
    _name, fields, media, *_ = inner.print_template.await_args.args
    assert fields["qr_url"] == "https://bridge.example.com/r/fil-1/spool-1"
    assert media == "62"


def test_print_unknown_csv_field_skipped(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    client = _client(db)
    # Override the CSV AFTER _client (which seeds a default CSV) — include an unknown name.
    set_config_value(db, "labelforge_fields", "brand, bogus , number")
    db.commit()
    inner = _mock_lfc(monkeypatch)

    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 200
    _name, fields, *_ = inner.print_template.await_args.args
    assert set(fields.keys()) == {"brand", "number"}  # bogus dropped


def test_print_passes_override_flag(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    client = _client(db)
    inner = _mock_lfc(monkeypatch)

    client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1", "override": True})
    assert inner.print_template.await_args.kwargs["override"] is True


# ===========================================================================
# api/labels — error surfacing
# ===========================================================================


def test_print_409_media_mismatch_surfaced(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    client = _client(db)
    _mock_lfc(monkeypatch, print_exc=LabelForgeError(
        "Printer has 29 loaded, template expects 62. Pass override=true to print anyway.",
        status_code=409,
        detail={"error": "media_mismatch", "override_allowed": True},
    ))
    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "media_mismatch"
    assert "override" in r.json()["detail"]["message"]


def test_print_400_error_passes_through(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    client = _client(db)
    _mock_lfc(monkeypatch, print_exc=LabelForgeError(
        "Missing required field: 'x'", status_code=400, detail="Missing required field: 'x'",
    ))
    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "labelforge_error"


def test_print_network_error_becomes_502(monkeypatch):
    db = _make_db()
    db.add(SpoolMapping(spoolman_spool_id=42, filamentdb_filament_id="fil-1", filamentdb_spool_id="spool-1"))
    client = _client(db)
    _mock_lfc(monkeypatch, print_exc=LabelForgeError(
        "Could not reach LabelForge: refused", status_code=None,
    ))
    r = client.post("/api/labels/print", json={"fil": "fil-1", "spool": "spool-1"})
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "labelforge_error"


# ===========================================================================
# api/labels — printer-status proxy
# ===========================================================================


def test_printer_status_proxy(monkeypatch):
    db = _make_db()
    client = _client(db)
    _mock_lfc(monkeypatch, status_return={"ready": True, "model": "QL-800", "loaded_media": None})
    r = client.get("/api/labels/printer-status")
    assert r.status_code == 200
    assert r.json()["ready"] is True
    assert r.json()["model"] == "QL-800"


def test_printer_status_403_when_disabled(monkeypatch):
    db = _make_db()
    client = _client(db, enabled=False)
    _mock_lfc(monkeypatch)
    r = client.get("/api/labels/printer-status")
    assert r.status_code == 403


def test_printer_status_400_when_not_configured(monkeypatch):
    db = _make_db()
    client = _client(db, configure=False)
    _mock_lfc(monkeypatch)
    r = client.get("/api/labels/printer-status")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "labelforge_not_configured"


def test_printer_status_network_error_becomes_502(monkeypatch):
    db = _make_db()
    client = _client(db)
    _mock_lfc(monkeypatch, status_exc=LabelForgeError(
        "Could not reach LabelForge: refused", status_code=None,
    ))
    r = client.get("/api/labels/printer-status")
    assert r.status_code == 502
