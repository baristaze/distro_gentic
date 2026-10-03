"""Station work leaves the queue: no claimant takes an item of its kind.

Revision ID: 202610035702
Revises: 202609280002
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610035702"
down_revision = "202609280002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035702_station_work_dropped.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035702_station_work_dropped.down.sql")
