"""Tests for core/change_log.py — formatting, append, rotation, robustness."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = datetime.timezone.utc
_NOW = datetime.datetime(2026, 6, 10, 21, 45, 3, tzinfo=_UTC)


def _now() -> datetime.datetime:
    return _NOW


# ---------------------------------------------------------------------------
# format_change_line — unit tests for the line formatter
# ---------------------------------------------------------------------------


class TestFormatChangeLine:
    from app.core.change_log import format_change_line

    def _fmt(self, **kw) -> str:
        from app.core.change_log import format_change_line
        defaults = dict(now=_NOW, action="update", direction="spoolman_to_filamentdb",
                        entity_type="spool")
        defaults.update(kw)
        return format_change_line(**defaults)

    def test_update_with_old_new(self):
        line = self._fmt(
            spoolman_id=42,
            fdb_spool_id="665f",
            field_name="remaining_weight",
            old_value=916.9,
            new_value=905.1,
            cycle_id="abc123",
        )
        assert "2026-06-10T21:45:03Z" in line
        assert "UPDATE" in line
        assert "filamentdb" in line
        assert "spool" in line
        assert "remaining_weight" in line
        assert "916.9" in line
        assert "905.1" in line
        assert "→" in line
        assert "(abc123)" in line

    def test_create_line(self):
        line = self._fmt(
            action="create",
            direction="spoolman_to_filamentdb",
            entity_type="filament",
            fdb_filament_id="665f1234",
            cycle_id="cycle42",
        )
        assert "CREATE" in line
        assert "filamentdb" in line
        assert "filament" in line
        assert "665f1234" in line
        assert "(cycle42)" in line

    def test_none_renders_as_dash(self):
        line = self._fmt(
            entity_type="filament",
            direction="filamentdb_to_spoolman",
            spoolman_id=7,
            field_name="type",
            old_value=None,
            new_value="PLA",
        )
        assert "—" in line
        assert "PLA" in line

    def test_delete_line(self):
        line = self._fmt(
            action="delete",
            direction="filamentdb_to_spoolman",
            entity_type="spool",
            spoolman_id=99,
        )
        assert "DELETE" in line
        assert "spoolman" in line

    def test_usage_line(self):
        line = self._fmt(
            action="usage",
            direction="spoolman_to_filamentdb",
            entity_type="spool",
            fdb_filament_id="fil1",
            fdb_spool_id="spool1",
            field_name="grams",
            new_value=10,
            cycle_id="c1",
        )
        assert "USAGE" in line
        assert "10" in line

    def test_json_encoded_string_unwrapped(self):
        """JSON-encoded extra values should be unwrapped to bare scalar."""
        from app.core.change_log import _render
        # simulate a Spoolman extra value: JSON-quoted string "916.9"
        assert _render(json.dumps(916.9)) == "916.9"
        assert _render(json.dumps("PLA")) == "PLA"

    def test_complex_value_compacted(self):
        from app.core.change_log import _render
        result = _render({"a": 1, "b": 2})
        assert result == '{"a":1,"b":2}'

    def test_no_cycle_id(self):
        line = self._fmt(spoolman_id=1)
        assert "(" not in line

    def test_filamentdb_to_spoolman_direction(self):
        line = self._fmt(
            action="update",
            direction="filamentdb_to_spoolman",
            entity_type="filament",
            spoolman_id=5,
        )
        assert "spoolman" in line

    def test_conflict_apply_direction(self):
        line = self._fmt(
            action="update",
            direction="conflict_apply",
            entity_type="filament",
            fdb_filament_id="abc",
        )
        assert "conflict_apply" in line


# ---------------------------------------------------------------------------
# record_change — append, rotation, write-failure robustness
# ---------------------------------------------------------------------------


class TestRecordChange:
    """Tests for record_change() with injected path and clock."""

    def _call(self, path: str, action: str = "update", **kw):
        from app.core.change_log import record_change
        kw.setdefault("direction", "spoolman_to_filamentdb")
        kw.setdefault("entity_type", "spool")
        kw.setdefault("spoolman_id", 42)
        record_change(
            action=action,
            _path=path,
            _enabled=True,
            _now=_now,
            **kw,
        )

    def test_appends_line(self, tmp_path):
        log = str(tmp_path / "changes.log")
        self._call(log, field_name="weight", old_value=100.0, new_value=90.0)
        lines = Path(log).read_text().splitlines()
        assert len(lines) == 1
        assert "UPDATE" in lines[0]

    def test_appends_multiple_lines(self, tmp_path):
        log = str(tmp_path / "changes.log")
        self._call(log, field_name="weight", old_value=100.0, new_value=90.0)
        self._call(log, action="create", entity_type="filament", fdb_filament_id="abc")
        lines = Path(log).read_text().splitlines()
        assert len(lines) == 2

    def test_skip_action_not_logged(self, tmp_path):
        """skip / info / conflict / error actions must NOT be written."""
        log = str(tmp_path / "changes.log")
        for non_mutation in ("skip", "info", "conflict", "error"):
            self._call(log, action=non_mutation)
        assert not os.path.exists(log)

    def test_disabled_flag(self, tmp_path):
        log = str(tmp_path / "changes.log")
        from app.core.change_log import record_change
        record_change(action="update", direction="spoolman_to_filamentdb",
                      entity_type="spool", spoolman_id=1,
                      _path=log, _enabled=False, _now=_now)
        assert not os.path.exists(log)

    def test_write_failure_swallowed(self, tmp_path):
        """A bad path (e.g. unwritable dir) must not raise into the caller."""
        bad_path = "/nonexistent_dir_xyz/changes.log"
        from app.core.change_log import record_change
        # Should not raise:
        record_change(action="update", direction="spoolman_to_filamentdb",
                      entity_type="spool", spoolman_id=1,
                      _path=bad_path, _enabled=True, _now=_now)

    def test_rotation_triggers_past_cap(self, tmp_path):
        """When the file exceeds _ROTATION_BYTES, it is rotated to .1."""
        from app.core import change_log as cl
        log = str(tmp_path / "changes.log")
        # Write a file larger than the cap.
        big_content = "x" * (cl._ROTATION_BYTES + 1)
        Path(log).write_text(big_content)
        # Call record_change — rotation should fire before the append.
        self._call(log)
        # Original file should be gone (rotated to .1).
        assert not os.path.exists(log) or Path(log).stat().st_size < cl._ROTATION_BYTES
        assert os.path.exists(f"{log}.1")
        # The .1 file should contain the big content.
        assert Path(f"{log}.1").read_text() == big_content

    def test_rotation_keeps_count(self, tmp_path):
        """Rotation shifts .1 → .2 → .3; .3 is overwritten by .2 when all full."""
        from app.core import change_log as cl
        log = str(tmp_path / "changes.log")
        big = "y" * (cl._ROTATION_BYTES + 1)
        # Pre-create .1 and .2
        Path(f"{log}.1").write_text("backup1")
        Path(f"{log}.2").write_text("backup2")
        Path(log).write_text(big)
        # Trigger rotation.
        self._call(log)
        assert os.path.exists(f"{log}.1")
        assert os.path.exists(f"{log}.2")
        # .3 was created (shifted from .2)
        assert os.path.exists(f"{log}.3")


# ---------------------------------------------------------------------------
# End-to-end-ish: _log in engine.py writes a changes.log line
# ---------------------------------------------------------------------------


class TestEngineIntegration:
    """Verify that a real sync engine update appends a line to changes.log."""

    @pytest.mark.asyncio
    async def test_update_produces_changes_log_entry(self, db, tmp_path):
        import json as _json

        from app.core.engine import run_sync_cycle
        from app.models.mapping import FilamentMapping, SpoolMapping
        from app.models.snapshot import Snapshot
        from app.schemas.filamentdb import FDBFilament
        from app.schemas.spoolman import SpoolmanFilament, SpoolmanSpool, SpoolmanVendor

        log_path = str(tmp_path / "changes.log")

        sm_spool = SpoolmanSpool(
            id=42,
            filament=SpoolmanFilament(
                id=10, name="PLA",
                vendor=SpoolmanVendor(id=1, name="ELEGOO"),
            ),
            remaining_weight=900.0,
            archived=False,
            extra={},
        )
        fdb_fil = FDBFilament.model_validate({
            "_id": "fil1",
            "name": "PLA",
            "vendor": "ELEGOO",
            "spoolWeight": 200.0,
            "spools": [{"_id": "sp1", "totalWeight": 1116.0, "retired": False}],
        })
        # After the weight change (SM dropped from 1016→900), snapshot totalWeight = 1216
        # so engine sees SM changed (916.9 in snap, now 900).
        # Simpler: SM has 900 remaining; FDB snapshot had 1116 → old net=916; now 900 → change.

        # Seed the filament/spool mapping.
        fil_map = FilamentMapping(
            spoolman_filament_id=10, filamentdb_id="fil1",
        )
        db.add(fil_map)
        db.flush()
        db.add(SpoolMapping(
            spoolman_spool_id=42, filamentdb_filament_id="fil1",
            filamentdb_spool_id="sp1", filament_mapping_id=fil_map.id,
        ))
        db.flush()

        # Seed snapshots: SM had remaining_weight=916.9; FDB had totalWeight=1116.9
        db.add(Snapshot(
            source="spoolman", entity_type="spool", entity_id="42",
            data=_json.dumps({"remaining_weight": 916.9}),
        ))
        db.add(Snapshot(
            source="filamentdb", entity_type="spool", entity_id="sp1",
            data=_json.dumps({"totalWeight": 1116.9}),
        ))
        db.flush()

        # Configure: spoolman → filamentdb weight sync
        from app.models.config import BridgeConfig
        db.merge(BridgeConfig(key="weight_sync_direction", value=_json.dumps("spoolman_to_filamentdb")))
        db.merge(BridgeConfig(key="weight_conflict_policy", value=_json.dumps("last_write_wins")))
        db.commit()

        sm_client = AsyncMock()
        sm_client.get_spools = AsyncMock(return_value=[sm_spool])
        sm_client.get_filaments = AsyncMock(return_value=[sm_spool.filament])
        sm_client.get_field_definitions = AsyncMock(return_value=[])
        sm_client.update_spool = AsyncMock(return_value=MagicMock())
        sm_client.health = AsyncMock(return_value={"version": "0.22.0"})

        fdb_client = AsyncMock()
        fdb_client.get_filaments = AsyncMock(return_value=[fdb_fil])
        fdb_client.get_filament = AsyncMock(return_value=None)
        fdb_client.get_version = AsyncMock(return_value="1.33.0")
        fdb_client.log_usage = AsyncMock(return_value={})
        fdb_client.update_spool = AsyncMock(return_value={})
        fdb_client.update_filament = AsyncMock(return_value={})

        # Run with real record_change pointing at our temp path.
        import app.core.change_log as cl_module
        original_record = cl_module.record_change

        def _patched_record(*, action, direction, entity_type, _path=None, _enabled=None, _now=None, **kw):
            original_record(
                action=action, direction=direction, entity_type=entity_type,
                _path=log_path, _enabled=True, _now=_now,
                **kw,
            )

        with patch.object(cl_module, "record_change", side_effect=_patched_record):
            await run_sync_cycle(
                db, sm_client, fdb_client,
                dry_run=False, cycle_id="test-e2e",
            )

        # There should be at least one UPDATE line in changes.log.
        assert os.path.exists(log_path), "changes.log was not created"
        content = Path(log_path).read_text()
        lines = [ln for ln in content.splitlines() if "UPDATE" in ln]
        assert lines, f"No UPDATE line in changes.log:\n{content}"
        # The weight field should appear.
        assert any("weight" in ln.lower() or "916" in ln or "900" in ln for ln in lines), (
            f"No weight-related UPDATE line:\n{content}"
        )
