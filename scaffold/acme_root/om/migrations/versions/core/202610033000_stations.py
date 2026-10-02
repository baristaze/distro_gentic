"""A tenant's labs, station pools, stations, daemon credentials, line, leases,
and jobs, each with its fence.

Revision ID: 202610033000
Revises: 202610032600
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610033000"
down_revision = "202610032600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610033000_stations.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610033000_stations.down.sql")
