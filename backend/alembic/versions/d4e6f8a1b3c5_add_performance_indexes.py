"""add performance indexes

Adds indexes for the hot query paths that were doing full-table scans:
- sync_log.timestamp   — ORDER BY timestamp DESC (+ MAX(timestamp), retention prune cutoff)
- sync_log.cycle_id    — window-mode GROUP BY / IN subquery
- conflicts.resolved_at        — the ubiquitous "open conflicts" (resolved_at IS NULL) filter
- filament_mappings.filamentdb_id      — value lookups during sync
- spool_mappings.filament_mapping_id   — FK join (SQLite does not auto-index FKs)

Index names match SQLAlchemy's index=True convention (ix_<table>_<column>) so a fresh
create_all and this migration produce the same schema.

Revision ID: d4e6f8a1b3c5
Revises: b7c2e1f4a9d3
Create Date: 2026-07-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e6f8a1b3c5"
down_revision: Union[str, Sequence[str], None] = "b7c2e1f4a9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_sync_log_timestamp", "sync_log", ["timestamp"])
    op.create_index("ix_sync_log_cycle_id", "sync_log", ["cycle_id"])
    op.create_index("ix_conflicts_resolved_at", "conflicts", ["resolved_at"])
    op.create_index(
        "ix_filament_mappings_filamentdb_id", "filament_mappings", ["filamentdb_id"]
    )
    op.create_index(
        "ix_spool_mappings_filament_mapping_id", "spool_mappings", ["filament_mapping_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_spool_mappings_filament_mapping_id", table_name="spool_mappings")
    op.drop_index("ix_filament_mappings_filamentdb_id", table_name="filament_mappings")
    op.drop_index("ix_conflicts_resolved_at", table_name="conflicts")
    op.drop_index("ix_sync_log_cycle_id", table_name="sync_log")
    op.drop_index("ix_sync_log_timestamp", table_name="sync_log")
