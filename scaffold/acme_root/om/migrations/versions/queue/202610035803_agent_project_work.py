"""The work a session sends to a host names the agent project it is for:
the key moves in place in every work item still held.

Revision ID: 202610035803
Revises: 202610035802
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610035803"
down_revision = "202610035802"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035803_agent_project_work.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.QUEUE, "202610035803_agent_project_work.down.sql")
