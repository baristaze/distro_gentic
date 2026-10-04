"""Work items are found by their target, for the reads that ask after one
session's latest item or whether it has one open.

Revision ID: 202610035802
Revises: 202610035702
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610035802"
down_revision = "202610035702"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035802_work_items_by_target.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035802_work_items_by_target.down.sql")
