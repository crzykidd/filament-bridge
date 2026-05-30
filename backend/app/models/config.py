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
    "multicolor_colorname_format": '"name"',
    "protect_multicolor_color_in_spoolman": "true",
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
