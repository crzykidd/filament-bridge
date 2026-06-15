from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("source", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)       # "spoolman" | "filamentdb"
    entity_type: Mapped[str] = mapped_column(String, nullable=False)  # "spool" | "filament"
    entity_id: Mapped[str] = mapped_column(String, nullable=False)    # Spoolman int or FDB ObjectId as string
    data: Mapped[str] = mapped_column(Text, nullable=False)           # full entity JSON blob
    captured_at: Mapped[object] = mapped_column(DateTime, nullable=False, default=func.now())
