"""Tests for _compute_name_collisions — vendor-aware collision detection.

Covers:
- cross-vendor same-name → no collision (false positive fix)
- same vendor+name vs existing FDB filament → vs_existing=True
- same vendor+name intra-batch (two incoming) → intra_batch=True
- already-linked cluster must NOT appear in preview name_collisions (generic_container mode)
- a genuinely-colliding created cluster DOES appear (no over-filtering)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import config, wizard
from app.api.config import set_config_value
from app.api.wizard import _compute_name_collisions
from app.core.planner import _FilamentPlanItem, _SyncPlan
from app.db import get_db
from app.models.mapping import FilamentMapping
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


def _fdb_filament_with_parent(fid: str, name: str, parent_id: str, vendor: str | None = None) -> FDBFilament:
    return FDBFilament.model_validate({
        "_id": fid,
        "name": name,
        "vendor": vendor,
        "parentId": parent_id,
    })


def test_container_name_reuses_existing_null_parent_container_no_collision():
    """A proposed container name matching an existing null-parent FDB container is REUSE
    (execute find-or-attach), not a collision — so no container-collision entry is emitted."""
    sm = _sm_filament(10, "PLA Black", "ELEGOO")
    plan = _plan_with_items([_create_plan_item(sm, "PLA Black", "ELEGOO")])
    # Existing container has NO parentId → reusable.
    existing = [_fdb_filament("fdb-container", "ELEGOO PLA (Master)", "ELEGOO")]
    container_names = {("elegoo", "pla", ""): "ELEGOO PLA (Master)"}

    collisions = _compute_name_collisions(plan, existing, container_names)

    container_cols = [c for c in collisions if c.is_container_collision]
    assert container_cols == [], (
        f"Existing null-parent container should be reused, not flagged: {container_cols}"
    )


def test_container_name_clash_with_variant_is_reported():
    """A proposed container name taken ONLY by a non-container record (a variant that has a
    parentId) is a genuine clash and IS reported — execute can't reuse a variant as a parent."""
    sm = _sm_filament(10, "PLA Black", "ELEGOO")
    plan = _plan_with_items([_create_plan_item(sm, "PLA Black", "ELEGOO")])
    # The only FDB filament with the container name is a VARIANT (has a parentId).
    existing = [_fdb_filament_with_parent("fdb-variant", "ELEGOO PLA (Master)", "some-parent", "ELEGOO")]
    container_names = {("elegoo", "pla", ""): "ELEGOO PLA (Master)"}

    collisions = _compute_name_collisions(plan, existing, container_names)

    container_cols = [c for c in collisions if c.is_container_collision]
    assert len(container_cols) == 1
    assert container_cols[0].vs_existing is True
    assert container_cols[0].existing_fdb_filament_id == "fdb-variant"


# ---------------------------------------------------------------------------
# Helpers for API-level preview tests (generic_container collision guard)
# ---------------------------------------------------------------------------


def _fake_spoolman_client(filaments=None, spools=None) -> AsyncMock:
    client = AsyncMock()
    client.get_spools = AsyncMock(return_value=spools or [])
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_vendors = AsyncMock(return_value=[])
    client.get_field_definitions = AsyncMock(return_value=[])
    client.ensure_extra_fields = AsyncMock(return_value=None)
    return client


def _fake_fdb_client(filaments=None) -> AsyncMock:
    client = AsyncMock()
    client.get_filaments = AsyncMock(return_value=filaments or [])
    client.get_filament = AsyncMock(return_value=None)
    client.get_version = AsyncMock(return_value="1.35.2")
    client.get_locations = AsyncMock(return_value=[])
    client.merge_filament_settings = AsyncMock(return_value=None)
    return client


def _preview_client(db, sm_client=None, fdb_client=None) -> TestClient:
    app = FastAPI()
    for mod in (config, wizard):
        app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.state.spoolman = sm_client or _fake_spoolman_client()
    app.state.filamentdb = fdb_client or _fake_fdb_client()
    return TestClient(app)


def _sm_fil(fid: int, name: str, vendor_name: str = "ELEGOO", material: str = "PLA") -> SpoolmanFilament:
    return SpoolmanFilament(
        id=fid,
        name=name,
        vendor=SpoolmanVendor(id=1, name=vendor_name),
        material=material,
    )


# ---------------------------------------------------------------------------
# Regression: already-linked cluster must NOT trigger container collision
# ---------------------------------------------------------------------------


def test_preview_already_linked_cluster_excluded_from_container_collisions(db):
    """generic_container: an already-linked cluster whose container name would collide with an
    existing FDB filament must NOT appear in name_collisions when the user only selected a
    DIFFERENT new filament.

    Regression for the bug where _preview_container_names was built from ALL
    item.resolved==True items (including already-linked skips), causing spurious
    container collision warnings.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    # User only selected the PETG filament (id=20) to create.
    # The PLA filament (id=10) is already linked — no decision needed.
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 20, "action": "create"},
    ])
    db.commit()

    # SM filament 10 (PLA) already has a FilamentMapping → planner will mark it
    # action="skip", resolved=True, detail="already linked".
    db.add(FilamentMapping(
        spoolman_filament_id=10,
        filamentdb_id="existing-pla-fdb",
        filamentdb_parent_id=None,
        is_synthetic_parent=False,
    ))
    db.commit()

    sm_pla = _sm_fil(10, "PLA Black", material="PLA")
    sm_petg = _sm_fil(20, "PETG Black", material="PETG")

    # FDB already has a filament named "ELEGOO PLA (Master)" — this is the name that
    # would be computed as the container display name for the already-linked PLA cluster.
    # The bug would report a vs_existing container collision for the PLA cluster even though
    # the user did not select it.
    existing_fdb = FDBFilament.model_validate({
        "_id": "fdb-pla-master",
        "name": "ELEGOO PLA (Master)",
        "vendor": "ELEGOO",
    })
    fdb_client = _fake_fdb_client(filaments=[existing_fdb])

    sm_client = _fake_spoolman_client(filaments=[sm_pla, sm_petg], spools=[])
    client = _preview_client(db, sm_client, fdb_client)

    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    collisions = body.get("name_collisions", [])
    # No container collision for the already-linked PLA cluster.
    container_collisions = [c for c in collisions if c.get("is_container_collision")]
    pla_collisions = [
        c for c in container_collisions
        if "pla" in (c.get("proposed_name") or "").lower()
    ]
    assert pla_collisions == [], (
        f"Already-linked PLA cluster must not appear in name_collisions, got: {pla_collisions}"
    )


def test_preview_existing_container_reused_not_collision(db):
    """generic_container: when the proposed container name already exists in FDB as a
    null-parent container, the cluster REUSES it (execute find-or-attach) and must NOT be
    flagged as a vs_existing collision — flagging it forced the whole cluster to be skipped.

    Regression for the reported bug: the user picked the existing FDB master in Variances,
    but the preview said "container name already exists — rename or skip" and the cluster
    got skipped instead of attaching the new variants to that master.
    """
    set_config_value(db, "import_direction", "spoolman")
    set_config_value(db, "variant_parent_mode", "generic_container")
    set_config_value(db, "wizard_match_decisions", [
        {"spoolman_filament_id": 10, "action": "create"},
    ])
    db.commit()

    sm_pla = _sm_fil(10, "PLA Black", material="PLA")

    # FDB already has "ELEGOO PLA (Master)" with NO parent → it's a reusable container.
    existing_fdb = FDBFilament.model_validate({
        "_id": "fdb-pla-master",
        "name": "ELEGOO PLA (Master)",
        "vendor": "ELEGOO",
    })
    fdb_client = _fake_fdb_client(filaments=[existing_fdb])
    sm_client = _fake_spoolman_client(filaments=[sm_pla], spools=[])
    client = _preview_client(db, sm_client, fdb_client)

    resp = client.get("/api/wizard/preview")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    collisions = body.get("name_collisions", [])
    container_collisions = [c for c in collisions if c.get("is_container_collision")]
    pla_collisions = [
        c for c in container_collisions
        if "pla" in (c.get("proposed_name") or "").lower()
    ]
    assert pla_collisions == [], (
        f"Existing null-parent container must be reused (no collision), got: {pla_collisions}"
    )
