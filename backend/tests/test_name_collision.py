"""Tests for _compute_name_collisions — vendor-aware collision detection.

Covers:
- cross-vendor same-name → no collision (false positive fix)
- same vendor+name vs existing FDB filament → vs_existing=True
- same vendor+name intra-batch (two incoming) → intra_batch=True
"""

from __future__ import annotations

from app.api.wizard import _compute_name_collisions
from app.core.planner import _FilamentPlanItem, _SyncPlan
from app.schemas.filamentdb import FDBFilament
from app.schemas.spoolman import SpoolmanFilament, SpoolmanVendor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fdb_filament(fid: str, name: str, vendor: str | None = None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": name,
        "vendor": vendor,
    })


def _sm_filament(fid: int, name: str, vendor_name: str) -> SpoolmanFilament:
    return SpoolmanFilament(
        id=fid,
        name=name,
        vendor=SpoolmanVendor(id=fid, name=vendor_name),
    )


def _create_plan_item(sm_fil: SpoolmanFilament, fdb_name: str, fdb_vendor: str | None) -> _FilamentPlanItem:
    return _FilamentPlanItem(
        sm_filament=sm_fil,
        action="create",
        fdb_payload={"name": fdb_name, "vendor": fdb_vendor},
    )


def _plan_with_items(items: list[_FilamentPlanItem]) -> _SyncPlan:
    plan = _SyncPlan()
    plan.filament_items = items
    return plan


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cross_vendor_same_name_no_collision():
    """Two incoming 'Beige' from different vendors and no existing same-vendor 'Beige' → no collision."""
    elegoo_fil = _sm_filament(1, "Beige", "ELEGOO")
    bambu_fil = _sm_filament(2, "Beige", "Bambu Lab")

    items = [
        _create_plan_item(elegoo_fil, "Beige", "ELEGOO"),
        _create_plan_item(bambu_fil, "Beige", "Bambu Lab"),
    ]
    plan = _plan_with_items(items)

    # Existing FDB filament: "Beige" but from a THIRD vendor (eSun)
    existing = [_fdb_filament("abc123", "Beige", "eSun")]

    collisions = _compute_name_collisions(plan, existing)

    # The two incoming are from different vendors → no intra_batch collision
    # Neither matches the existing eSun Beige by vendor → no vs_existing
    assert collisions == [], (
        f"Expected no collisions for cross-vendor same-name, got: {collisions}"
    )


def test_same_vendor_name_vs_existing():
    """Incoming filament with same vendor+name as an existing FDB filament → vs_existing=True."""
    elegoo_fil = _sm_filament(1, "PLA Beige", "ELEGOO")
    item = _create_plan_item(elegoo_fil, "PLA Beige", "ELEGOO")
    plan = _plan_with_items([item])

    # Existing FDB filament: same vendor+name (case-insensitive match)
    existing = [_fdb_filament("def456", "PLA Beige", "Elegoo")]

    collisions = _compute_name_collisions(plan, existing)

    assert len(collisions) == 1
    entry = collisions[0]
    assert entry.vs_existing is True
    assert entry.intra_batch is False
    assert entry.existing_fdb_filament_id == "def456"
    assert entry.normalized_name == "pla beige"


def test_same_vendor_name_intra_batch():
    """Two incoming SM filaments with same vendor+name → intra_batch=True."""
    fil_a = _sm_filament(10, "Matte PLA", "Bambu Lab")
    fil_b = _sm_filament(11, "Matte PLA", "BAMBU LAB")  # normalized same vendor

    items = [
        _create_plan_item(fil_a, "Matte PLA", "Bambu Lab"),
        _create_plan_item(fil_b, "Matte PLA", "BAMBU LAB"),
    ]
    plan = _plan_with_items(items)

    collisions = _compute_name_collisions(plan, [])

    assert len(collisions) == 1
    entry = collisions[0]
    assert entry.intra_batch is True
    assert entry.vs_existing is False
    assert set(entry.sm_filament_ids) == {10, 11}
