"""Each tenant's retention policy and each session's snapshot of it, with
their fence.

Revision ID: 202610031300
Revises: 202610030900
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610031300"
down_revision = "202610030900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610031300_retention.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610031300_retention.down.sql")
