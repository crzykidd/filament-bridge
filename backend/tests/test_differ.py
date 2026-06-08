"""Tests for core/differ.py — changeset classification."""


from app.core.differ import diff_spool_pair
from app.core.fields import FieldMapping
from app.schemas.filamentdb import FDBSpool
from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool

THRESHOLD = 2.0


def _sm_spool(spool_id: int, remaining: float, extra: dict | None = None) -> SpoolmanSpool:
    return SpoolmanSpool(
        id=spool_id,
        filament=SpoolmanFilament(id=1, name="PLA"),
        remaining_weight=remaining,
        extra=extra or {},
    )


def _fdb_spool(spool_id: str, total: float) -> FDBSpool:
    return FDBSpool(**{"_id": spool_id, "totalWeight": total})


def _sm_snap(remaining: float) -> dict:
    return {"remaining_weight": remaining}


def _fdb_snap(total: float) -> dict:
    return {"totalWeight": total}


class TestDiffSpoolPair:
    def test_no_prior_snapshot_returns_no_change(self):
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=None, fdb_snapshot=None, threshold=THRESHOLD,
        )
        assert cs.has_prior_snapshot is False
        assert cs.sm_weight_change is None
        assert cs.fdb_weight_change is None
        assert not cs.weight_conflict

    def test_no_change(self):
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=_sm_snap(800.0), fdb_snapshot=_fdb_snap(1000.0), threshold=THRESHOLD,
        )
        assert cs.sm_weight_change is None
        assert cs.fdb_weight_change is None
        assert not cs.weight_conflict

    def test_sm_weight_decreased(self):
        cs = diff_spool_pair(
            _sm_spool(1, 795.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=_sm_snap(800.0), fdb_snapshot=_fdb_snap(1000.0), threshold=THRESHOLD,
        )
        assert cs.sm_weight_change is not None
        assert cs.sm_weight_change.old_value == 800.0
        assert cs.sm_weight_change.new_value == 795.0
        assert cs.fdb_weight_change is None
        assert not cs.weight_conflict

    def test_fdb_weight_changed(self):
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1050.0), "fdb-fil-1",
            sm_snapshot=_sm_snap(800.0), fdb_snapshot=_fdb_snap(1000.0), threshold=THRESHOLD,
        )
        assert cs.fdb_weight_change is not None
        assert cs.sm_weight_change is None
        assert not cs.weight_conflict

    def test_both_changed_is_conflict(self):
        cs = diff_spool_pair(
            _sm_spool(1, 790.0), _fdb_spool("a", 1050.0), "fdb-fil-1",
            sm_snapshot=_sm_snap(800.0), fdb_snapshot=_fdb_snap(1000.0), threshold=THRESHOLD,
        )
        assert cs.weight_conflict is True
        assert cs.sm_weight_change is not None
        assert cs.fdb_weight_change is not None

    def test_below_threshold_not_detected(self):
        cs = diff_spool_pair(
            _sm_spool(1, 799.5), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=_sm_snap(800.0), fdb_snapshot=_fdb_snap(1000.0), threshold=THRESHOLD,
        )
        assert cs.sm_weight_change is None
        assert not cs.weight_conflict

    def test_exactly_at_threshold_detected(self):
        cs = diff_spool_pair(
            _sm_spool(1, 798.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=_sm_snap(800.0), fdb_snapshot=_fdb_snap(1000.0), threshold=THRESHOLD,
        )
        assert cs.sm_weight_change is not None


def _color_fm() -> FieldMapping:
    return FieldMapping(fdb_path="color", sm_key="color", direction="sm_to_fdb")


def _snaps_with_color(sm_color: str, fdb_color: str) -> tuple[dict, dict]:
    sm_snap = {"remaining_weight": 800.0, "_extra_decoded": {"color": sm_color}}
    fdb_snap = {"totalWeight": 1000.0, "_field_values": {"color": fdb_color}}
    return sm_snap, fdb_snap


class TestColorNormalizationInDiffer:
    """Bare-vs-# representation differences must not cause spurious field changes."""

    def test_bare_sm_vs_hash_fdb_no_flap(self):
        sm_snap, fdb_snap = _snaps_with_color("93BE2F", "#93BE2F")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_color_fm()],
            sm_extra_decoded={"color": "93BE2F"},
            fdb_field_values={"color": "#93BE2F"},
        )
        assert not cs.sm_field_changes
        assert not cs.fdb_field_changes
        assert not cs.field_conflicts

    def test_hash_sm_vs_hash_fdb_same_color_no_flap(self):
        sm_snap, fdb_snap = _snaps_with_color("#93BE2F", "#93BE2F")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_color_fm()],
            sm_extra_decoded={"color": "#93BE2F"},
            fdb_field_values={"color": "#93BE2F"},
        )
        assert not cs.sm_field_changes
        assert not cs.fdb_field_changes

    def test_case_difference_no_flap(self):
        sm_snap, fdb_snap = _snaps_with_color("93be2f", "#93BE2F")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_color_fm()],
            sm_extra_decoded={"color": "93be2f"},
            fdb_field_values={"color": "#93BE2F"},
        )
        assert not cs.sm_field_changes
        assert not cs.fdb_field_changes

    def test_real_color_change_detected(self):
        """A genuine color change (not just a # prefix difference) is still caught."""
        sm_snap, fdb_snap = _snaps_with_color("FF0000", "#FF0000")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_color_fm()],
            sm_extra_decoded={"color": "00FF00"},   # SM changed to green
            fdb_field_values={"color": "#FF0000"},  # FDB still red
        )
        assert len(cs.sm_field_changes) == 1
        assert cs.sm_field_changes[0].field_name == "color"

    def test_round_trip_convergence(self):
        """Simulated SM→FDB→SM: second cycle sees no color change."""
        from app.core.color import to_fdb_color, to_sm_color

        original_sm = "93BE2F"
        fdb_written = to_fdb_color(original_sm)   # "#93BE2F" — what wizard writes
        sm_written = to_sm_color(fdb_written)      # "93BE2F" — what engine writes back

        # Second cycle: snapshot reflects the written values; current values are the same
        sm_snap, fdb_snap = _snaps_with_color(sm_written, fdb_written)
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_color_fm()],
            sm_extra_decoded={"color": sm_written},
            fdb_field_values={"color": fdb_written},
        )
        assert not cs.sm_field_changes
        assert not cs.fdb_field_changes
        assert not cs.field_conflicts


def _type_material_fm() -> FieldMapping:
    """FieldMapping for FDB 'type' ↔ Spoolman 'material'."""
    return FieldMapping(fdb_path="type", sm_key="material", direction="sm_to_fdb")


def _snaps_with_material(sm_material: str, fdb_type: str) -> tuple[dict, dict]:
    sm_snap = {"remaining_weight": 800.0, "_extra_decoded": {"material": sm_material}}
    fdb_snap = {"totalWeight": 1000.0, "_field_values": {"type": fdb_type}}
    return sm_snap, fdb_snap


class TestFinishStrippedTypeDiffer:
    """SM 'material' ↔ FDB 'type' comparison must strip finish keywords from SM side
    so 'PLA Silk' ↔ 'PLA' is treated as no-change (flap-safe)."""

    def test_pla_silk_vs_pla_no_flap(self):
        """'PLA Silk' (SM) vs 'PLA' (FDB) should not be detected as a change."""
        sm_snap, fdb_snap = _snaps_with_material("PLA Silk", "PLA")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_type_material_fm()],
            sm_extra_decoded={"material": "PLA Silk"},
            fdb_field_values={"type": "PLA"},
        )
        assert not cs.sm_field_changes, "PLA Silk vs PLA should not appear as SM change"
        assert not cs.fdb_field_changes
        assert not cs.field_conflicts

    def test_pla_matte_vs_pla_no_flap(self):
        sm_snap, fdb_snap = _snaps_with_material("PLA Matte", "PLA")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_type_material_fm()],
            sm_extra_decoded={"material": "PLA Matte"},
            fdb_field_values={"type": "PLA"},
        )
        assert not cs.sm_field_changes
        assert not cs.field_conflicts

    def test_petg_silk_vs_petg_no_flap(self):
        sm_snap, fdb_snap = _snaps_with_material("PETG Silk", "PETG")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_type_material_fm()],
            sm_extra_decoded={"material": "PETG Silk"},
            fdb_field_values={"type": "PETG"},
        )
        assert not cs.sm_field_changes

    def test_pla_vs_petg_still_detected_as_real_change(self):
        """A genuine material change (PLA → PETG) must still be detected."""
        sm_snap, fdb_snap = _snaps_with_material("PLA", "PLA")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_type_material_fm()],
            sm_extra_decoded={"material": "PETG"},  # SM changed to PETG
            fdb_field_values={"type": "PLA"},       # FDB still PLA
        )
        assert len(cs.sm_field_changes) == 1
        assert cs.sm_field_changes[0].field_name == "type"

    def test_snapshot_pla_silk_vs_current_pla_silk_and_fdb_pla_no_flap(self):
        """Round-trip: snapshot has 'PLA Silk' on SM and 'PLA' on FDB; same on current → NOOP."""
        sm_snap, fdb_snap = _snaps_with_material("PLA Silk", "PLA")
        cs = diff_spool_pair(
            _sm_spool(1, 800.0), _fdb_spool("a", 1000.0), "fdb-fil-1",
            sm_snapshot=sm_snap, fdb_snapshot=fdb_snap, threshold=THRESHOLD,
            field_maps=[_type_material_fm()],
            sm_extra_decoded={"material": "PLA Silk"},
            fdb_field_values={"type": "PLA"},
        )
        assert not cs.sm_field_changes
        assert not cs.fdb_field_changes
        assert not cs.field_conflicts
