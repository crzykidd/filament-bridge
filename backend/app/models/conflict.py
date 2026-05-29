from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)  # "spool" | "filament"
    spoolman_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filamentdb_filament_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    filamentdb_spool_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    spoolman_value: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON-encoded
    filamentdb_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded
    detected_at: Mapped[object] = mapped_column(DateTime, nullable=False, default=func.now())
    resolved_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)  # "spoolman" | "filamentdb" | "manual"
    resolved_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded
