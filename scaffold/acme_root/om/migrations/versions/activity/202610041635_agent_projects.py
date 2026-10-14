"""A run and a validation name the agent project whose key they ran for,
and the kinds of the events an agent project announced move in place.
Every row stays.

Revision ID: 202610041635
Revises: 202610041634
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610041635"
down_revision = "202610041634"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041635_agent_projects.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.ACTIVITY, "202610041635_agent_projects.down.sql")
