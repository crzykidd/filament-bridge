"""filament_mapping: nullable spoolman_filament_id + is_synthetic_parent column

Revision ID: a1b2c3d4e5f6
Revises: 9e504c864be4
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9e504c864be4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make spoolman_filament_id nullable and add is_synthetic_parent column.

    SQLite does not support ALTER COLUMN, so we use the standard SQLite
    column-rename workaround:
      1. Add a new nullable column ``spoolman_filament_id_new`` (nullable=True).
      2. Copy values from the old column.
      3. Drop the old column (SQLite 3.35+ supports DROP COLUMN; for older
         SQLite we do a full table-rebuild via batch mode).
      4. Rename the new column to the canonical name.

    In practice, Alembic's ``batch_alter_table`` handles the table-rebuild path
    transparently for SQLite, so we use it unconditionally.

    The UNIQUE constraint on ``spoolman_filament_id`` is preserved — SQLite
    allows multiple NULLs under a UNIQUE constraint, so synthetic-parent rows
    (spoolman_filament_id = NULL) do not collide.
    """
    with op.batch_alter_table("filament_mappings", recreate="always") as batch_op:
        # Make spoolman_filament_id nullable (keep unique).
        batch_op.alter_column(
            "spoolman_filament_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        # Add is_synthetic_parent with a server-side default of 0 (False).
        batch_op.add_column(
            sa.Column(
                "is_synthetic_parent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    """Reverse: drop is_synthetic_parent and restore spoolman_filament_id NOT NULL.

    Any rows where spoolman_filament_id IS NULL (synthetic parents) will
    violate the NOT NULL constraint on downgrade — those rows must be removed
    first or the migration will fail.  In practice, downgrade is only used in
    test environments.
    """
    with op.batch_alter_table("filament_mappings", recreate="always") as batch_op:
        batch_op.drop_column("is_synthetic_parent")
        batch_op.alter_column(
            "spoolman_filament_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
