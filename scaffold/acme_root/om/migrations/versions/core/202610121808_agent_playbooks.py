"""A playbook is an agent playbook, and the one pinned to a kind is its
kind manual: the three tables, their columns, and their indexes take the
names, every row stays, and an agent automation's action names its agent
playbook, and the outbox's event kinds move in place.

Revision ID: 202610121808
Revises: 202610121807
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121808"
down_revision = "202610121807"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121808_agent_playbooks.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121808_agent_playbooks.down.sql")
