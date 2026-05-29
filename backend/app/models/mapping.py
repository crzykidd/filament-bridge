from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class FilamentMapping(Base):
    __tablename__ = "filament_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spoolman_filament_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    filamentdb_id: Mapped[str] = mapped_column(String(24), nullable=False)
    filamentdb_parent_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )


class SpoolMapping(Base):
    __tablename__ = "spool_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spoolman_spool_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    filamentdb_filament_id: Mapped[str] = mapped_column(String(24), nullable=False)
    filamentdb_spool_id: Mapped[str] = mapped_column(String(24), nullable=False)
    filament_mapping_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("filament_mappings.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[object] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
