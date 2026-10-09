"""Each tenant's projects and the project each session belongs to, with
their fence.

Revision ID: 202610091911
Revises: 202610091910
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091911"
down_revision = "202610091910"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091911_projects.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091911_projects.down.sql")
