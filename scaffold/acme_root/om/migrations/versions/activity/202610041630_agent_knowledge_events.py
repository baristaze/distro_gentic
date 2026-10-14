"""Knowledge is agent knowledge: the kinds of the events it announced move
in place.

Revision ID: 202610041630
Revises: 202610041629
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041630"
down_revision = "202610041629"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041630_agent_knowledge_events.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041630_agent_knowledge_events.down.sql")
