"""A session's notifications are read by the session.

Revision ID: 202610091932
Revises: 202610091931
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091932"
down_revision = "202610091931"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091932_notifications_by_their_session.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091932_notifications_by_their_session.down.sql")
