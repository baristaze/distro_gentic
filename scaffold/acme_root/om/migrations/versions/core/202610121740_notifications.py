"""Whose authority an automation runs on, the tenant's automation principal
with its fence, a user's accounts read as their channels, and the
notifications a park sends, with their fence.

Revision ID: 202610121740
Revises: 202610121739
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121740"
down_revision = "202610121739"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121740_notifications.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121740_notifications.down.sql")
