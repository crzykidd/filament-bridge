"""index spool_mappings.filamentdb_spool_id

Follow-up to the performance-index pass (d4e6f8a1b3c5). An index deep-dive found one
more clearly high-value miss: spool_mappings is looked up by filamentdb_spool_id on the
mobile-scan resolve path (per request) and the orphan-spool re-adoption pass (per spool
per sync cycle), and that column led no existing index (only spoolman_spool_id is unique).

Index name matches SQLAlchemy's index=True convention (ix_<table>_<column>).

Revision ID: e5f7a2c4b6d8
Revises: d4e6f8a1b3c5
Create Date: 2026-07-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "e5f7a2c4b6d8"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a1b3c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_spool_mappings_filamentdb_spool_id",
        "spool_mappings",
        ["filamentdb_spool_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_spool_mappings_filamentdb_spool_id", table_name="spool_mappings"
    )
