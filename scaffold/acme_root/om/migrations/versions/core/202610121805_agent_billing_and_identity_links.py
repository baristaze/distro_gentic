"""Agent billing's account is a spend account on a unit plan, and intake's
link of an outside identity to a user is an identity link: the tables,
their columns, and their indexes take the names, every row stays, and
the outbox's event kinds move in place.

Revision ID: 202610121805
Revises: 202610121804
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121805"
down_revision = "202610121804"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121805_agent_billing_and_identity_links.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121805_agent_billing_and_identity_links.down.sql")
