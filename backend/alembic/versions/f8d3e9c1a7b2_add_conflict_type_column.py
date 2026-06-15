"""Add conflict_type column to conflicts table.

Existing rows default to 'cross_system' (the standard both-sides-changed conflict).
The new 'master_divergence' type is queued when a SM→FDB write would set a value on a
variant that diverges from its inherited master value; these are record-only pending
Phase B approval.

Revision ID: f8d3e9c1a7b2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8d3e9c1a7b2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add conflict_type column (default 'cross_system') to conflicts table."""
    with op.batch_alter_table("conflicts", recreate="auto") as batch_op:
        batch_op.add_column(
            sa.Column(
                "conflict_type",
                sa.String(),
                nullable=False,
                server_default="cross_system",
            )
        )


def downgrade() -> None:
    """Remove conflict_type column from conflicts table."""
    with op.batch_alter_table("conflicts", recreate="auto") as batch_op:
        batch_op.drop_column("conflict_type")
