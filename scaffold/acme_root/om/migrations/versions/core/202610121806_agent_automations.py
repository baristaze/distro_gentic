"""An automation is an agent automation: its three tables, their columns,
and their indexes take the name, every row stays, and the stored values
that named it move in place: the principal it runs as, the names of its
two tools, and its events' kinds in the outbox.

Revision ID: 202610121806
Revises: 202610121805
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121806"
down_revision = "202610121805"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121806_agent_automations.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121806_agent_automations.down.sql")
