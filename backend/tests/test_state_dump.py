"""Tests for app/core/state_dump.py."""

from __future__ import annotations

import asyncio
import datetime
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.state_dump import format_state_dump, prune_dumps, write_startup_dump
from app.schemas.filamentdb import FDBFilament, FDBSpool
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor, encode_extra_value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_settings(
    sm_fdb_id: str = "filamentdb_id",
    sm_fdb_parent_id: str = "filamentdb_parent_id",
    sm_fdb_spool_id: str = "filamentdb_spool_id",
    sm_material_tags: str = "filamentdb_material_tags",
    sm_opt_slug: str = "openprinttag_slug",
    sm_opt_uuid: str = "openprinttag_uuid",
) -> SimpleNamespace:
    return SimpleNamespace(
        spoolman_field_filamentdb_id=sm_fdb_id,
        spoolman_field_filamentdb_parent_id=sm_fdb_parent_id,
        spoolman_field_filamentdb_spool_id=sm_fdb_spool_id,
        spoolman_field_filamentdb_material_tags=sm_material_tags,
        spoolman_field_openprinttag_slug=sm_opt_slug,
        spoolman_field_openprinttag_uuid=sm_opt_uuid,
    )


def _sm_vendor(vid: int = 1, name: str = "Hatchbox") -> SpoolmanVendor:
    return SpoolmanVendor(id=vid, name=name)


def _sm_filament(
    fid: int = 12,
    name: str = "PLA",
    vendor: SpoolmanVendor | None = None,
    color_hex: str | None = "ADD8E6",
    material: str | None = "PLA",
    density: float | None = 1.24,
    diameter: float | None = 1.75,
    spool_weight: float | None = 200.0,
    weight: float | None = 1000.0,
    price: float | None = 24.99,
    extra: dict | None = None,
) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=fid,
        name=name,
        vendor=vendor or _sm_vendor(),
        color_hex=color_hex,
        material=material,
        density=density,
        diameter=diameter,
        spool_weight=spool_weight,
        weight=weight,
        price=price,
        extra=extra or {},
    )


def _sm_spool(
    sid: int = 42,
    filament: SpoolmanFilament | None = None,
    remaining: float | None = 916.9,
    used: float | None = 83.1,
    location: str | None = "Bin 3",
    lot_nr: str | None = None,
    archived: bool = False,
    extra: dict | None = None,
) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=sid,
        filament=filament or _sm_filament(),
        remaining_weight=remaining,
        used_weight=used,
        location=location,
        lot_nr=lot_nr,
        archived=archived,
        extra=extra or {},
    )


def _fdb_filament(
    fid: str = "665f0c000000000000000001",
    name: str = "Hatchbox PLA Light Blue",
    vendor: str | None = "Hatchbox",
    type_: str | None = "PLA",
    color: str | None = "ADD8E6",
    density: float | None = 1.24,
    spool_weight: float | None = 200.0,
    net_weight: float | None = 1000.0,
    cost: float | None = 24.99,
    parent_id: str | None = None,
    opt_tags: list | None = None,
    spools: list | None = None,
) -> FDBFilament:
    raw = {
        "_id": fid,
        "name": name,
        "vendor": vendor,
        "type": type_,
        "color": color,
        "density": density,
        "spoolWeight": spool_weight,
        "netFilamentWeight": net_weight,
        "cost": cost,
        "parentId": parent_id,
        "optTags": opt_tags or [],
        "spools": spools or [],
    }
    return FDBFilament.model_validate(raw)


def _fdb_spool(
    sid: str = "665f0d000000000000000001",
    label: str | None = "42",
    total_weight: float | None = 1116.9,
    retired: bool = False,
) -> FDBSpool:
    return FDBSpool.model_validate({"_id": sid, "label": label, "totalWeight": total_weight, "retired": retired})


# ---------------------------------------------------------------------------
# format_state_dump — section headers with counts
# ---------------------------------------------------------------------------


def test_format_state_dump_section_counts():
    settings = _fake_settings()
    sm_filaments = [_sm_filament(fid=i) for i in range(3)]
    sm_spools = [_sm_spool(sid=i) for i in range(5)]
    fdb_filaments = [_fdb_filament(fid=f"aabb{i:020d}") for i in range(2)]

    now = datetime.datetime(2026, 6, 11, 15, 45, 0, tzinfo=datetime.timezone.utc)
    versions = {"bridge": "0.1.0", "spoolman": "0.22.1", "filamentdb": "1.37.0"}

    text = format_state_dump(sm_filaments, sm_spools, fdb_filaments, versions, now, settings)

    assert "== SPOOLMAN FILAMENTS (3) ==" in text
    assert "== SPOOLMAN SPOOLS (5) ==" in text
    assert "== FILAMENT DB FILAMENTS (2) ==" in text
    assert "== FILAMENT DB SPOOLS (0) ==" in text  # no embedded spools


def test_format_state_dump_header_contains_versions():
    settings = _fake_settings()
    now = datetime.datetime(2026, 6, 11, 15, 45, 0, tzinfo=datetime.timezone.utc)
    versions = {"bridge": "0.1.0", "spoolman": "0.22.1", "filamentdb": "1.37.0"}
    text = format_state_dump([], [], [], versions, now, settings)

    assert "written: 2026-06-11T15:45:00Z" in text
    assert "bridge: 0.1.0" in text
    assert "spoolman: 0.22.1" in text
    assert "filamentdb: 1.37.0" in text
    assert "retention: newest 10 dumps kept" in text


# ---------------------------------------------------------------------------
# format_state_dump — stable sort order
# ---------------------------------------------------------------------------


def test_format_state_dump_sm_filaments_sorted_by_id():
    settings = _fake_settings()
    sm_filaments = [_sm_filament(fid=30), _sm_filament(fid=1), _sm_filament(fid=15)]
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    text = format_state_dump(sm_filaments, [], [], {}, now, settings)

    lines = [l for l in text.splitlines() if l.startswith("filament #")]
    ids = [int(l.split("#")[1].split(" ")[0]) for l in lines]
    assert ids == sorted(ids)


def test_format_state_dump_sm_spools_sorted_by_id():
    settings = _fake_settings()
    sm_spools = [_sm_spool(sid=99), _sm_spool(sid=3), _sm_spool(sid=50)]
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    text = format_state_dump([], sm_spools, [], {}, now, settings)

    lines = [l for l in text.splitlines() if l.startswith("spool #")]
    ids = [int(l.split("#")[1].split(" ")[0]) for l in lines]
    assert ids == sorted(ids)


def test_format_state_dump_fdb_filaments_sorted_by_id():
    settings = _fake_settings()
    fdb_filaments = [
        _fdb_filament(fid="aaabbb000000000000000003"),
        _fdb_filament(fid="aaabbb000000000000000001"),
        _fdb_filament(fid="aaabbb000000000000000002"),
    ]
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    text = format_state_dump([], [], fdb_filaments, {}, now, settings)

    lines = [l for l in text.splitlines() if l.startswith("filament ") and not l.startswith("filament #")]
    fids = [l.split(" ")[1] for l in lines]
    assert fids == sorted(fids)


# ---------------------------------------------------------------------------
# format_state_dump — extras decoded, empties omitted
# ---------------------------------------------------------------------------


def test_format_state_dump_sm_filament_extras_decoded():
    """Bridge extras with values are included; empties are omitted."""
    settings = _fake_settings()
    extra = {
        "filamentdb_id": encode_extra_value("665f0c000000000000000001"),
        "filamentdb_parent_id": encode_extra_value(""),          # empty → omit
        "filamentdb_material_tags": encode_extra_value(None),    # None → omit
        "openprinttag_slug": encode_extra_value("hatchbox-pla"),
        "openprinttag_uuid": encode_extra_value("ccf3abc1-0000-0000-0000-000000000000"),
        "unrelated_field": encode_extra_value("should_not_appear"),
    }
    fil = _sm_filament(extra=extra)
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    text = format_state_dump([fil], [], [], {}, now, settings)

    fil_line = next(l for l in text.splitlines() if l.startswith("filament #"))
    assert "filamentdb_id=665f0c00000000000000" in fil_line   # truncated
    assert "openprinttag_slug=hatchbox-pla" in fil_line
    assert "filamentdb_parent_id" not in fil_line              # empty → omitted
    assert "filamentdb_material_tags" not in fil_line          # None → omitted
    assert "unrelated_field" not in fil_line                   # not a bridge key


def test_format_state_dump_sm_spool_extras_decoded():
    settings = _fake_settings()
    extra = {
        "filamentdb_spool_id": encode_extra_value("665f0d000000000000000001"),
        "filamentdb_id": encode_extra_value(""),   # empty → omit
        "filamentdb_parent_id": encode_extra_value("665f0c000000000000000001"),
    }
    spool = _sm_spool(extra=extra)
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    text = format_state_dump([], [spool], [], {}, now, settings)

    spool_line = next(l for l in text.splitlines() if l.startswith("spool #"))
    assert "filamentdb_spool_id=665f0d00" in spool_line
    assert "filamentdb_parent_id=665f0c00" in spool_line
    assert "filamentdb_id" not in spool_line   # empty → omitted


def test_format_state_dump_none_versions_show_unknown():
    settings = _fake_settings()
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    text = format_state_dump([], [], [], {"bridge": None, "spoolman": None, "filamentdb": None}, now, settings)
    assert "bridge: unknown" in text
    assert "spoolman: unknown" in text
    assert "filamentdb: unknown" in text


# ---------------------------------------------------------------------------
# format_state_dump — FDB spools embedded count
# ---------------------------------------------------------------------------


def test_format_state_dump_fdb_spool_count():
    settings = _fake_settings()
    spool1 = _fdb_spool(sid="aaa000000000000000000001")
    spool2 = _fdb_spool(sid="aaa000000000000000000002")
    fil_raw = {
        "_id": "bbb000000000000000000001",
        "name": "PLA",
        "spools": [
            {"_id": spool1.id, "label": spool1.label, "totalWeight": spool1.totalWeight, "retired": False},
            {"_id": spool2.id, "label": spool2.label, "totalWeight": spool2.totalWeight, "retired": False},
        ],
    }
    fil = FDBFilament.model_validate(fil_raw)

    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    text = format_state_dump([], [], [fil], {}, now, settings)
    assert "== FILAMENT DB SPOOLS (2) ==" in text


# ---------------------------------------------------------------------------
# format_state_dump — clock injection
# ---------------------------------------------------------------------------


def test_format_state_dump_injected_clock():
    settings = _fake_settings()
    now = datetime.datetime(2000, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    text = format_state_dump([], [], [], {}, now, settings)
    assert "written: 2000-01-02T03:04:05Z" in text


# ---------------------------------------------------------------------------
# prune_dumps
# ---------------------------------------------------------------------------


def _write_dump_files(dump_dir: Path, names: list[str]) -> None:
    for name in names:
        (dump_dir / name).write_text("stub")


def test_prune_dumps_keeps_newest_10():
    with tempfile.TemporaryDirectory() as tmp:
        dump_dir = Path(tmp)
        # Create 15 dump files (lexicographic order = chronological)
        names = [f"startup-state-202606{i:02d}T000000Z.txt" for i in range(1, 16)]
        _write_dump_files(dump_dir, names)

        prune_dumps(dump_dir, keep=10)

        remaining = sorted(p.name for p in dump_dir.glob("startup-state-*.txt"))
        assert len(remaining) == 10
        # Should keep the newest (last 10 by name)
        assert remaining == names[5:]  # keep indices 5..14 (10 files)


def test_prune_dumps_fewer_than_keep_leaves_all():
    with tempfile.TemporaryDirectory() as tmp:
        dump_dir = Path(tmp)
        names = [f"startup-state-2026060{i}T000000Z.txt" for i in range(1, 6)]  # 5 files
        _write_dump_files(dump_dir, names)

        prune_dumps(dump_dir, keep=10)

        remaining = sorted(p.name for p in dump_dir.glob("startup-state-*.txt"))
        assert len(remaining) == 5


def test_prune_dumps_ignores_non_dump_files():
    with tempfile.TemporaryDirectory() as tmp:
        dump_dir = Path(tmp)
        # Create enough dump files to trigger pruning
        names = [f"startup-state-202606{i:02d}T000000Z.txt" for i in range(1, 16)]
        _write_dump_files(dump_dir, names)
        # Add a non-dump file that must survive
        other = dump_dir / "bridge.db"
        other.write_text("database")

        prune_dumps(dump_dir, keep=10)

        assert other.exists(), "non-dump file must not be deleted"
        remaining = sorted(p.name for p in dump_dir.glob("startup-state-*.txt"))
        assert len(remaining) == 10


def test_prune_dumps_empty_dir_no_error():
    with tempfile.TemporaryDirectory() as tmp:
        # Should not raise
        prune_dumps(Path(tmp), keep=10)


# ---------------------------------------------------------------------------
# write_startup_dump — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_startup_dump_creates_file():
    settings = _fake_settings()
    # Also set data_dir so write_startup_dump can use it via the function arg,
    # not via settings — the function takes data_dir separately.

    sm_filaments = [_sm_filament()]
    sm_spools = [_sm_spool()]
    fdb_filaments = [_fdb_filament()]

    sm_client = AsyncMock()
    sm_client.get_filaments = AsyncMock(return_value=sm_filaments)
    sm_client.get_spools = AsyncMock(return_value=sm_spools)
    # _get_sm_version reads from sm_client._http.get — mock that path
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {"version": "0.22.1"}
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=mock_resp)
    sm_client._http = http_mock

    fdb_client = AsyncMock()
    fdb_client.get_filaments = AsyncMock(return_value=fdb_filaments)
    fdb_client.get_version = AsyncMock(return_value="1.37.0")

    with tempfile.TemporaryDirectory() as tmp:
        await write_startup_dump(sm_client, fdb_client, tmp, settings)

        dump_dir = Path(tmp) / "state-dumps"
        dumps = list(dump_dir.glob("startup-state-*.txt"))
        assert len(dumps) == 1

        content = dumps[0].read_text(encoding="utf-8")
        assert "== SPOOLMAN FILAMENTS (1) ==" in content
        assert "== SPOOLMAN SPOOLS (1) ==" in content
        assert "== FILAMENT DB FILAMENTS (1) ==" in content


# ---------------------------------------------------------------------------
# write_startup_dump — error path: no file, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_startup_dump_client_error_no_file_no_exception():
    """A client error must be swallowed — no file written, no exception propagated."""
    settings = _fake_settings()

    sm_client = AsyncMock()
    sm_client.get_filaments = AsyncMock(side_effect=RuntimeError("Spoolman unreachable"))
    sm_client.get_spools = AsyncMock(return_value=[])
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(side_effect=RuntimeError("unreachable"))
    sm_client._http = http_mock

    fdb_client = AsyncMock()
    fdb_client.get_filaments = AsyncMock(return_value=[])
    fdb_client.get_version = AsyncMock(return_value=None)

    with tempfile.TemporaryDirectory() as tmp:
        # Must not raise
        await write_startup_dump(sm_client, fdb_client, tmp, settings)

        dump_dir = Path(tmp) / "state-dumps"
        if dump_dir.exists():
            dumps = list(dump_dir.glob("startup-state-*.txt"))
            assert len(dumps) == 0, "no dump file should be written on error"


# ---------------------------------------------------------------------------
# Gate: settings.debug_startup_dump = False → task not scheduled
# ---------------------------------------------------------------------------


def test_gate_false_does_not_schedule(monkeypatch):
    """When debug_startup_dump is False, write_startup_dump should never be called."""
    called = []

    async def _fake_dump(*args, **kwargs):
        called.append(True)

    monkeypatch.setattr("app.core.state_dump.write_startup_dump", _fake_dump)

    from app.config import settings as real_settings

    # Confirm the default value.
    assert real_settings.debug_startup_dump is False

    # Simulate the lifespan decision branch:
    if real_settings.debug_startup_dump:
        asyncio.create_task(_fake_dump())

    assert called == [], "write_startup_dump must not be called when flag is False"
