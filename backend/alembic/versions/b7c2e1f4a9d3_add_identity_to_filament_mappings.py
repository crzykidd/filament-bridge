"""Add identity JSON column to filament_mappings.

Persists {vendor, name, color_hex, material} at FilamentMapping creation time
so build_mapping_rows can display filament-only rows without a spool snapshot.
Nullable — existing rows degrade gracefully (build_mapping_rows falls back to None).
No data migration; existing rows self-heal on next sync via opportunistic backfill.

Revision ID: b7c2e1f4a9d3
Revises: f8d3e9c1a7b2
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c2e1f4a9d3"
down_revision: Union[str, Sequence[str], None] = "f8d3e9c1a7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable identity column to filament_mappings."""
    with op.batch_alter_table("filament_mappings", recreate="auto") as batch_op:
        batch_op.add_column(
            sa.Column("identity", sa.String(), nullable=True)
        )


def downgrade() -> None:
    """Remove identity column from filament_mappings."""
    with op.batch_alter_table("filament_mappings", recreate="auto") as batch_op:
        batch_op.drop_column("identity")
