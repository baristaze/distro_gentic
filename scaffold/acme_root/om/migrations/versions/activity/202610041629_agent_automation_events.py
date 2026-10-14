"""An automation is an agent automation: the kinds of the events it
announced move in place.

Revision ID: 202610041629
Revises: 202610041628
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041629"
down_revision = "202610041628"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041629_agent_automation_events.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041629_agent_automation_events.down.sql")
