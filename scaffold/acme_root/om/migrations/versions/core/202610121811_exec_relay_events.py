"""The platform's relay is the exec relay, apart from the outbox's: the
kinds of the events it announces move in place in the outbox.

Revision ID: 202610121811
Revises: 202610121810
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121811"
down_revision = "202610121810"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121811_exec_relay_events.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121811_exec_relay_events.down.sql")
