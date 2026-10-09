"""Each tenant's retention policy and each session's snapshot of it, with
their fence.

Revision ID: 202610091908
Revises: 202610091907
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091908"
down_revision = "202610091907"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091908_retention.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091908_retention.down.sql")
