"""Exhaustive unit tests for core/sync_policy.py — pure resolver, no I/O."""

import datetime
import json

import pytest

from app.core.sync_policy import SyncAction, resolve_sync_action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(hour: int) -> datetime.datetime:
    """Return a UTC datetime at the given hour on 2025-01-01."""
    return datetime.datetime(2025, 1, 1, hour, 0, 0, tzinfo=datetime.timezone.utc)


EARLY = _dt(1)
LATE  = _dt(2)


# ---------------------------------------------------------------------------
# No-change → always NOOP regardless of direction/policy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("direction", ["two_way", "spoolman_to_filamentdb", "filamentdb_to_spoolman"])
@pytest.mark.parametrize("policy", ["manual", "spoolman_wins", "filamentdb_wins", "newest_wins"])
def test_noop_when_nothing_changed(direction, policy):
    action = resolve_sync_action(
        sm_changed=False, fdb_changed=False,
        direction=direction, policy=policy,
    )
    assert action == SyncAction.NOOP


# ---------------------------------------------------------------------------
# One-way: spoolman_to_filamentdb
# ---------------------------------------------------------------------------

def test_sm_only_changed_sm_to_fdb_direction():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=False,
        direction="spoolman_to_filamentdb", policy="manual",
    )
    assert action == SyncAction.PUSH_SM_TO_FDB


def test_fdb_only_changed_sm_to_fdb_direction_is_noop():
    """Locked destination (FDB) drifted — one-way never queues a conflict, just NOOP."""
    action = resolve_sync_action(
        sm_changed=False, fdb_changed=True,
        direction="spoolman_to_filamentdb", policy="manual",
    )
    assert action == SyncAction.NOOP


def test_both_changed_sm_to_fdb_direction_pushes_sm_no_conflict():
    """Both changed but direction is one-way SM→FDB: SM wins, no conflict queued."""
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="spoolman_to_filamentdb", policy="manual",
    )
    assert action == SyncAction.PUSH_SM_TO_FDB


# ---------------------------------------------------------------------------
# One-way: filamentdb_to_spoolman
# ---------------------------------------------------------------------------

def test_fdb_only_changed_fdb_to_sm_direction():
    action = resolve_sync_action(
        sm_changed=False, fdb_changed=True,
        direction="filamentdb_to_spoolman", policy="manual",
    )
    assert action == SyncAction.PUSH_FDB_TO_SM


def test_sm_only_changed_fdb_to_sm_direction_is_noop():
    """Locked destination (SM) drifted — NOOP, no conflict."""
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=False,
        direction="filamentdb_to_spoolman", policy="manual",
    )
    assert action == SyncAction.NOOP


def test_both_changed_fdb_to_sm_direction_pushes_fdb_no_conflict():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="filamentdb_to_spoolman", policy="manual",
    )
    assert action == SyncAction.PUSH_FDB_TO_SM


# ---------------------------------------------------------------------------
# Two-way: lone changes always propagate
# ---------------------------------------------------------------------------

def test_two_way_lone_sm_change_propagates():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=False,
        direction="two_way", policy="manual",
    )
    assert action == SyncAction.PUSH_SM_TO_FDB


def test_two_way_lone_fdb_change_propagates():
    action = resolve_sync_action(
        sm_changed=False, fdb_changed=True,
        direction="two_way", policy="manual",
    )
    assert action == SyncAction.PUSH_FDB_TO_SM


# ---------------------------------------------------------------------------
# Two-way: conflict policies
# ---------------------------------------------------------------------------

def test_two_way_manual_both_changed_queues_conflict():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="manual",
    )
    assert action == SyncAction.QUEUE_CONFLICT


def test_two_way_spoolman_wins_both_changed():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="spoolman_wins",
    )
    assert action == SyncAction.PUSH_SM_TO_FDB


def test_two_way_filamentdb_wins_both_changed():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="filamentdb_wins",
    )
    assert action == SyncAction.PUSH_FDB_TO_SM


# ---------------------------------------------------------------------------
# Two-way: newest_wins
# ---------------------------------------------------------------------------

def test_newest_wins_sm_newer():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="newest_wins",
        sm_ts=LATE, fdb_ts=EARLY,
    )
    assert action == SyncAction.PUSH_SM_TO_FDB


def test_newest_wins_fdb_newer():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="newest_wins",
        sm_ts=EARLY, fdb_ts=LATE,
    )
    assert action == SyncAction.PUSH_FDB_TO_SM


def test_newest_wins_equal_timestamps_falls_back_to_conflict():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="newest_wins",
        sm_ts=EARLY, fdb_ts=EARLY,
    )
    assert action == SyncAction.QUEUE_CONFLICT


def test_newest_wins_missing_sm_ts_falls_back_to_conflict():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="newest_wins",
        sm_ts=None, fdb_ts=LATE,
    )
    assert action == SyncAction.QUEUE_CONFLICT


def test_newest_wins_missing_fdb_ts_falls_back_to_conflict():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="newest_wins",
        sm_ts=EARLY, fdb_ts=None,
    )
    assert action == SyncAction.QUEUE_CONFLICT


def test_newest_wins_both_missing_falls_back_to_conflict():
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=True,
        direction="two_way", policy="newest_wins",
        sm_ts=None, fdb_ts=None,
    )
    assert action == SyncAction.QUEUE_CONFLICT


def test_newest_wins_not_consulted_for_lone_changes():
    """newest_wins is a both-changed policy; lone SM change → PUSH_SM regardless."""
    action = resolve_sync_action(
        sm_changed=True, fdb_changed=False,
        direction="two_way", policy="newest_wins",
        sm_ts=None, fdb_ts=None,  # timestamps missing but irrelevant
    )
    assert action == SyncAction.PUSH_SM_TO_FDB


# ---------------------------------------------------------------------------
# Migration idempotency
# ---------------------------------------------------------------------------

@pytest.fixture
def _fresh_db():
    """In-memory SQLite session with BridgeConfig seeded."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db import Base
    from app.models.config import seed_defaults

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_defaults(session)
    return session


def test_migration_maps_spoolman_sot_to_sm_to_fdb_direction(_fresh_db):
    """Old weight_source_of_truth=spoolman → weight_sync_direction=spoolman_to_filamentdb."""
    from app.api.config import get_config_value, set_config_value
    from app.main import _migrate_sync_config

    db = _fresh_db
    set_config_value(db, "weight_source_of_truth", "spoolman")
    db.commit()

    _migrate_sync_config(db)

    assert get_config_value(db, "weight_sync_direction") == "spoolman_to_filamentdb"
    assert get_config_value(db, "weight_conflict_policy") == "manual"


def test_migration_maps_filamentdb_sot_to_fdb_to_sm_direction(_fresh_db):
    """Old material_properties_source_of_truth=filamentdb → filamentdb_to_spoolman."""
    from app.api.config import get_config_value, set_config_value
    from app.main import _migrate_sync_config

    db = _fresh_db
    set_config_value(db, "material_properties_source_of_truth", "filamentdb")
    db.commit()

    _migrate_sync_config(db)

    assert get_config_value(db, "material_properties_sync_direction") == "filamentdb_to_spoolman"
    assert get_config_value(db, "material_properties_conflict_policy") == "manual"


def test_migration_is_idempotent(_fresh_db):
    """Running migrate twice does not overwrite explicitly set new keys."""
    from app.api.config import get_config_value, set_config_value
    from app.main import _migrate_sync_config

    db = _fresh_db
    # Pre-set the new keys (simulates a post-migration state)
    set_config_value(db, "weight_sync_direction", "two_way")
    set_config_value(db, "weight_conflict_policy", "spoolman_wins")
    set_config_value(db, "material_properties_sync_direction", "two_way")
    set_config_value(db, "material_properties_conflict_policy", "filamentdb_wins")
    db.commit()

    # Run migration twice
    _migrate_sync_config(db)
    _migrate_sync_config(db)

    # New keys must survive unchanged
    assert get_config_value(db, "weight_sync_direction") == "two_way"
    assert get_config_value(db, "weight_conflict_policy") == "spoolman_wins"
    assert get_config_value(db, "material_properties_sync_direction") == "two_way"
    assert get_config_value(db, "material_properties_conflict_policy") == "filamentdb_wins"


def test_migration_fresh_install_sets_sm_to_fdb_for_weight(_fresh_db):
    """Fresh install (no old SoT keys) gets the same default as old SM SoT."""
    from app.api.config import get_config_value
    from app.main import _migrate_sync_config

    db = _fresh_db
    # No old SoT keys present — defaults from seed_defaults apply (spoolman for weight)
    _migrate_sync_config(db)

    assert get_config_value(db, "weight_sync_direction") == "spoolman_to_filamentdb"
    assert get_config_value(db, "material_properties_sync_direction") == "filamentdb_to_spoolman"
