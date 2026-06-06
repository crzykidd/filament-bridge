from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base

_DEFAULTS = {
    "weight_source_of_truth": '"spoolman"',
    "material_properties_source_of_truth": '"filamentdb"',
    "new_spool_source_of_truth": '"spoolman"',
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
