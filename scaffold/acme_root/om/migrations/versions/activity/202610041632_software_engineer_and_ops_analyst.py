"""The engineer kind is the software engineer and the operator kind the ops
analyst: usage records and pin events carry the new kind ids.

Revision ID: 202610041632
Revises: 202610041631
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041632"
down_revision = "202610041631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041632_software_engineer_and_ops_analyst.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041632_software_engineer_and_ops_analyst.down.sql")
