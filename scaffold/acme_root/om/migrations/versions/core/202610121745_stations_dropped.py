"""The stations leave the core role: the secrets declared on a station,
then each fence, then each table.

Revision ID: 202610121745
Revises: 202610121744
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121745"
down_revision = "202610121744"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121745_stations_dropped.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121745_stations_dropped.down.sql")
