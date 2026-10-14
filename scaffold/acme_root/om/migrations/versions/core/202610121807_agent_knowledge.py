"""Knowledge is agent knowledge: its two tables and their indexes take the
name, every entry and recall stays, and the stored values that named it
move in place: the names of its three tools, and its events' kinds in
the outbox.

Revision ID: 202610121807
Revises: 202610121806
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121807"
down_revision = "202610121806"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121807_agent_knowledge.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121807_agent_knowledge.down.sql")
