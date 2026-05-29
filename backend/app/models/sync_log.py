from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String, nullable=False)  # UUID grouping one sync run
    timestamp: Mapped[object] = mapped_column(DateTime, nullable=False, default=func.now())
    direction: Mapped[str] = mapped_column(String, nullable=False)  # "spoolman_to_filamentdb" | "filamentdb_to_spoolman"
    action: Mapped[str] = mapped_column(String, nullable=False)     # "create" | "update" | "conflict" | "skip" | "error"
    entity_type: Mapped[str] = mapped_column(String, nullable=False)  # "spool" | "filament"
    spoolman_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filamentdb_filament_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    filamentdb_spool_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    field_name: Mapped[str | None] = mapped_column(String, nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
