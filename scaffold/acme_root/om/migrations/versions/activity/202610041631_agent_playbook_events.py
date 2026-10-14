"""A playbook is an agent playbook: the kinds of the events it announced
move in place.

Revision ID: 202610041631
Revises: 202610041630
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041631"
down_revision = "202610041630"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041631_agent_playbook_events.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041631_agent_playbook_events.down.sql")
