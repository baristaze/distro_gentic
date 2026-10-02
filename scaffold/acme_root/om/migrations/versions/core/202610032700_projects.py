"""Each tenant's projects and the project each session belongs to, with
their fence.

Revision ID: 202610032700
Revises: 202610032300
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610032700"
down_revision = "202610032300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032700_projects.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610032700_projects.down.sql")
