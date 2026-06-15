from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class FilamentMapping(Base):
    __tablename__ = "filament_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL for synthetic container parents (generic_container mode): SQLite allows
    # multiple NULLs under a UNIQUE constraint, so the uniqueness invariant holds
    # for all real (non-null) Spoolman filament ids.
    spoolman_filament_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    filamentdb_id: Mapped[str] = mapped_column(String(24), nullable=False)
    filamentdb_parent_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # True when this mapping represents a bridge-owned synthetic container parent
    # (created in generic_container variant_parent_mode).  Synthetic parents have
    # spoolman_filament_id = NULL and are excluded from sync/orphan detection.
    is_synthetic_parent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON blob {vendor, name, color_hex, material} written at FilamentMapping creation
    # time (wizard execute + single_record_import).  NULL for legacy rows and synthetic
    # parents; build_mapping_rows degrades gracefully on NULL.
    identity: Mapped[str | None] = mapped_column(String, nullable=True)
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
