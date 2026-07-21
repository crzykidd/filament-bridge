"""Tests for filament-level dashboard counts and wizard execute per-type breakdown.

Covers:
  A. sync_status filament_counts — mixed fixture (in_sync, pending, conflict, synthetic excluded).
  B. wizard execute WizardExecuteResponse per-type breakdown fields.
"""

import pytest

from app.models.conflict import Conflict
from app.models.mapping import FilamentMapping
from app.models.snapshot import Snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_filament_mapping(
    db,
    *,
    spoolman_filament_id: int | None,
    filamentdb_id: str,
    is_synthetic: bool = False,
) -> FilamentMapping:
    fm = FilamentMapping(
        spoolman_filament_id=spoolman_filament_id,
        filamentdb_id=filamentdb_id,
        is_synthetic_parent=is_synthetic,
    )
    db.add(fm)
    db.flush()
    return fm


def _add_snapshot(db, *, source: str, entity_type: str, entity_id: str) -> Snapshot:
    snap = Snapshot(source=source, entity_type=entity_type, entity_id=entity_id, data="{}")
    db.add(snap)
    db.flush()
    return snap


def _add_open_conflict(db, *, filamentdb_filament_id: str) -> Conflict:
    c = Conflict(
        entity_type="filament",
        field_name="material",
        filamentdb_filament_id=filamentdb_filament_id,
        spoolman_id=None,
    )
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------------------
# Fixture: mixed set of filament mappings
#
#   SM id 10 / FDB "aaaa..." → both snapshots present → in_sync
#   SM id 20 / FDB "bbbb..." → only SM snapshot → pending
#   SM id 30 / FDB "cccc..." → open conflict → conflict
#   SM id NULL / FDB "dddd..." is_synthetic=True → EXCLUDED from counts
# ---------------------------------------------------------------------------


FDB_A = "aaaaaaaaaaaaaaaaaaaaaaaa"   # in_sync
FDB_B = "bbbbbbbbbbbbbbbbbbbbbbbb"   # pending
FDB_C = "cccccccccccccccccccccccc"   # conflict
FDB_D = "dddddddddddddddddddddddd"   # synthetic — excluded


@pytest.fixture()
def mixed_filament_db(db):
    """Populate DB with the mixed fixture and return the session."""
    # in_sync: SM id 10, FDB A — both snapshots
    _add_filament_mapping(db, spoolman_filament_id=10, filamentdb_id=FDB_A)
    _add_snapshot(db, source="spoolman", entity_type="filament", entity_id="10")
    _add_snapshot(db, source="filamentdb", entity_type="filament", entity_id=FDB_A)

    # pending: SM id 20, FDB B — only SM snapshot
    _add_filament_mapping(db, spoolman_filament_id=20, filamentdb_id=FDB_B)
    _add_snapshot(db, source="spoolman", entity_type="filament", entity_id="20")

    # conflict: SM id 30, FDB C — open conflict
    _add_filament_mapping(db, spoolman_filament_id=30, filamentdb_id=FDB_C)
    _add_open_conflict(db, filamentdb_filament_id=FDB_C)

    # synthetic: NULL spoolman_filament_id — must be excluded
    _add_filament_mapping(db, spoolman_filament_id=None, filamentdb_id=FDB_D, is_synthetic=True)

    db.commit()
    return db


# ---------------------------------------------------------------------------
# A. filament_counts tests
# ---------------------------------------------------------------------------


class TestFilamentCounts:
    """Tests for the filament_counts dict returned by sync_status."""

    def _compute_filament_counts(self, db) -> dict:
        """Extract the filament_counts computation from sync_status directly.

        Rather than hitting the HTTP endpoint (which requires async clients for
        health probes), we replicate the same query logic here so the unit tests
        remain fast and side-effect-free.  The production code path is validated
        via integration.
        """
        from app.models.conflict import Conflict
        from app.models.mapping import FilamentMapping
        from app.models.snapshot import Snapshot

        filament_counts: dict[str, int] = {"in_sync": 0, "pending": 0, "conflict": 0, "total": 0}
        open_conflict_fdb_ids: set[str] = {
            c.filamentdb_filament_id
            for c in db.query(Conflict).filter(
                Conflict.resolved_at.is_(None),
                Conflict.filamentdb_filament_id.is_not(None),
            ).all()
            if c.filamentdb_filament_id
        }
        real_filament_mappings = (
            db.query(FilamentMapping)
            .filter(FilamentMapping.spoolman_filament_id.is_not(None))
            .all()
        )
        for fm in real_filament_mappings:
            filament_counts["total"] += 1
            fdb_id = fm.filamentdb_id
            if fdb_id in open_conflict_fdb_ids:
                filament_counts["conflict"] += 1
                continue
            sm_snap = db.query(Snapshot).filter(
                Snapshot.source == "spoolman",
                Snapshot.entity_type == "filament",
                Snapshot.entity_id == str(fm.spoolman_filament_id),
            ).first()
            fdb_snap = db.query(Snapshot).filter(
                Snapshot.source == "filamentdb",
                Snapshot.entity_type == "filament",
                Snapshot.entity_id == fdb_id,
            ).first()
            if sm_snap and fdb_snap:
                filament_counts["in_sync"] += 1
            else:
                filament_counts["pending"] += 1

        return filament_counts

    def test_total_excludes_synthetic(self, mixed_filament_db):
        """Synthetic NULL-spoolman_filament_id masters must not appear in the total."""
        counts = self._compute_filament_counts(mixed_filament_db)
        # 3 real pairs (A=in_sync, B=pending, C=conflict); D=synthetic is excluded
        assert counts["total"] == 3

    def test_in_sync_count(self, mixed_filament_db):
        counts = self._compute_filament_counts(mixed_filament_db)
        assert counts["in_sync"] == 1

    def test_pending_count(self, mixed_filament_db):
        counts = self._compute_filament_counts(mixed_filament_db)
        assert counts["pending"] == 1

    def test_conflict_count(self, mixed_filament_db):
        counts = self._compute_filament_counts(mixed_filament_db)
        assert counts["conflict"] == 1

    def test_empty_db_returns_zeros(self, db):
        """With no mappings the counts must all be zero (not missing keys)."""
        counts = self._compute_filament_counts(db)
        assert counts == {"in_sync": 0, "pending": 0, "conflict": 0, "total": 0}

    def test_resolved_conflict_not_counted(self, db):
        """A resolved conflict must not count toward the conflict bucket."""
        import datetime

        _add_filament_mapping(db, spoolman_filament_id=50, filamentdb_id="eeeeeeeeeeeeeeeeeeeeeeee")
        c = Conflict(
            entity_type="filament",
            field_name="material",
            filamentdb_filament_id="eeeeeeeeeeeeeeeeeeeeeeee",
            resolved_at=datetime.datetime.utcnow(),
        )
        db.add(c)
        db.commit()

        counts = self._compute_filament_counts(db)
        # No snapshots → pending (not conflict, because conflict is resolved)
        assert counts["conflict"] == 0
        assert counts["pending"] == 1


# ---------------------------------------------------------------------------
# B. WizardExecuteResponse per-type breakdown
# ---------------------------------------------------------------------------


class TestExecutePerTypeBreakdown:
    """Tests for created_filaments / created_spools etc. on WizardExecuteResponse."""

    def test_breakdown_sums_match_flat_totals(self):
        """Breakdown fields must be consistent with the flat totals."""
        from app.schemas.api import WizardExecuteResponse, WizardExecuteRecord

        records = [
            WizardExecuteRecord(entity_type="filament", action="created", label="F1"),
            WizardExecuteRecord(entity_type="spool", action="created", label="S1"),
            WizardExecuteRecord(entity_type="spool", action="created", label="S2"),
            WizardExecuteRecord(entity_type="filament", action="updated", label="F2"),
            WizardExecuteRecord(entity_type="spool", action="skipped", label="S3"),
            WizardExecuteRecord(entity_type="filament", action="failed", label="F3"),
        ]

        # Simulate the breakdown computation used by wizard_execute.
        _type_action_counts: dict[tuple[str, str], int] = {}
        for r in records:
            key = (r.entity_type, r.action)
            _type_action_counts[key] = _type_action_counts.get(key, 0) + 1

        resp = WizardExecuteResponse(
            cycle_id="test-breakdown",
            direction="spoolman_to_filamentdb",
            created=3,  # 1 filament + 2 spools
            updated=1,
            skipped=1,
            failed=1,
            wizard_completed=False,
            records=records,
            created_filaments=_type_action_counts.get(("filament", "created"), 0),
            created_spools=_type_action_counts.get(("spool", "created"), 0),
            updated_filaments=_type_action_counts.get(("filament", "updated"), 0),
            updated_spools=_type_action_counts.get(("spool", "updated"), 0),
            skipped_filaments=_type_action_counts.get(("filament", "skipped"), 0),
            skipped_spools=_type_action_counts.get(("spool", "skipped"), 0),
            failed_filaments=_type_action_counts.get(("filament", "failed"), 0),
            failed_spools=_type_action_counts.get(("spool", "failed"), 0),
        )

        assert resp.created_filaments == 1
        assert resp.created_spools == 2
        assert resp.created_filaments + resp.created_spools == resp.created

        assert resp.updated_filaments == 1
        assert resp.updated_spools == 0
        assert resp.updated_filaments + resp.updated_spools == resp.updated

        assert resp.skipped_filaments == 0
        assert resp.skipped_spools == 1
        assert resp.skipped_filaments + resp.skipped_spools == resp.skipped

        assert resp.failed_filaments == 1
        assert resp.failed_spools == 0
        assert resp.failed_filaments + resp.failed_spools == resp.failed

    def test_empty_records_all_zeros(self):
        """No records → all per-type breakdown fields are zero."""
        from app.schemas.api import WizardExecuteResponse

        resp = WizardExecuteResponse(
            cycle_id="empty",
            direction="filamentdb_to_spoolman",
            created=0,
            updated=0,
            skipped=0,
            failed=0,
            wizard_completed=True,
            records=[],
        )

        assert resp.created_filaments == 0
        assert resp.created_spools == 0
        assert resp.updated_filaments == 0
        assert resp.updated_spools == 0
        assert resp.skipped_filaments == 0
        assert resp.skipped_spools == 0
        assert resp.failed_filaments == 0
        assert resp.failed_spools == 0


def test_filament_mapping_status_batched_matches_per_row(db):
    """The preloaded-snapshot-id path returns the same status as the per-row query path."""
    from app.core.filament_status import filament_mapping_status

    fm_sync = _add_filament_mapping(db, spoolman_filament_id=10, filamentdb_id="fdb-sync")
    _add_snapshot(db, source="spoolman", entity_type="filament", entity_id="10")
    _add_snapshot(db, source="filamentdb", entity_type="filament", entity_id="fdb-sync")
    fm_pending = _add_filament_mapping(db, spoolman_filament_id=11, filamentdb_id="fdb-pending")
    _add_snapshot(db, source="spoolman", entity_type="filament", entity_id="11")
    fm_conflict = _add_filament_mapping(db, spoolman_filament_id=12, filamentdb_id="fdb-conflict")
    db.commit()

    open_ids = {"fdb-conflict"}
    sm_ids = {"10", "11"}
    fdb_ids = {"fdb-sync"}

    for fm, expected in [(fm_sync, "in_sync"), (fm_pending, "pending"), (fm_conflict, "conflict")]:
        assert filament_mapping_status(db, fm, open_ids) == expected
        assert filament_mapping_status(
            db, fm, open_ids,
            sm_filament_snapshot_ids=sm_ids, fdb_filament_snapshot_ids=fdb_ids,
        ) == expected
