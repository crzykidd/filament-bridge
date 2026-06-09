from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base

_DEFAULTS = {
    "weight_source_of_truth": '"spoolman"',
    "material_properties_source_of_truth": '"filamentdb"',
    "auto_sync_enabled": "false",
    "sync_weight_threshold_grams": "2.0",
    "weight_precision_decimals": "2",
    "wizard_completed": "false",
    # New two-axis sync direction + conflict policy keys.
    # Values here are migration-safe defaults: both categories start one-way
    # (mirrors old SoT defaults) with manual conflict policy.
    "weight_sync_direction": '"spoolman_to_filamentdb"',
    "weight_conflict_policy": '"manual"',
    "material_properties_sync_direction": '"filamentdb_to_spoolman"',
    "material_properties_conflict_policy": '"manual"',
    # New spool creation direction: two_way = bidirectional (= today's behavior).
    "new_spool_sync_direction": '"two_way"',
    # Spoolman vendor → OpenTag brand aliases for the OpenTag cleanup matcher.
    # Empty string = no aliases (default).
    "opentag_vendor_aliases": '""',
    # Runtime-configurable sync interval (seconds). 0 = use env-default.
    "sync_interval_seconds": "0",
    # Sync-log retention in days. 0 = keep forever.
    "sync_log_retention_days": "30",
    # When true, the wizard import skips creating FDB spool records for spools
    # whose remaining net weight is 0 (empty/depleted). The filament definition
    # is still imported; only the empty spool inventory record is excluded.
    "never_import_empties": "false",
    # Debug mode: when true, exposes the /api/debug/* reset endpoints for clean
    # re-testing (clear Spoolman FDB xrefs; reset bridge local state).
    # Off by default; never enable in production.
    "debug_mode": "false",
}


class BridgeConfig(Base):
    __tablename__ = "bridge_config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded
    updated_at: Mapped[object] = mapped_column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )


def seed_defaults(db) -> None:
    from sqlalchemy.dialects.sqlite import insert

    for key, value in _DEFAULTS.items():
        stmt = insert(BridgeConfig).values(key=key, value=value).on_conflict_do_nothing()
        db.execute(stmt)
    db.commit()
