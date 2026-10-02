"""The relay's exec items with how they ended, the parts of their output,
the control messages for the host that holds them, and the host that holds
each session's workspace, each with its fence.

Revision ID: 202610034100
Revises: 202610033700
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610034100"
down_revision = "202610033700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034100_relay.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610034100_relay.down.sql")
