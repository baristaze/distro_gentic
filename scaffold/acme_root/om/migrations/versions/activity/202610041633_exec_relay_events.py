"""The platform's relay is the exec relay, apart from the outbox's: the
kinds of the events it announced move in place.

Revision ID: 202610041633
Revises: 202610041632
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041633"
down_revision = "202610041632"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041633_exec_relay_events.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041633_exec_relay_events.down.sql")
