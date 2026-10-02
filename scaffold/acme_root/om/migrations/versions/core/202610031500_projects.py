"""Each tenant's projects and the project each session belongs to, with
their fence.

Revision ID: 202610031500
Revises: 202610032100
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610031500"
down_revision = "202610032100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610031500_projects.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610031500_projects.down.sql")
