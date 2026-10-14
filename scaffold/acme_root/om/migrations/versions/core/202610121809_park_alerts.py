"""A notification that a parked session waits on a person is a park alert:
the table and its indexes take the name, and every row stays.

Revision ID: 202610121809
Revises: 202610121808
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121809"
down_revision = "202610121808"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121809_park_alerts.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121809_park_alerts.down.sql")
