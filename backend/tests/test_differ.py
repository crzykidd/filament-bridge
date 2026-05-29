"""Tests for core/differ.py — changeset classification."""

import pytest

from app.core.differ import diff_spool_pair
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
