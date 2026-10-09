"""A tenant's labs, station pools, stations, daemon credentials, line, leases,
and jobs, each with its fence.

Revision ID: 202610091916
Revises: 202610091915
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091916"
down_revision = "202610091915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091916_stations.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091916_stations.down.sql")
