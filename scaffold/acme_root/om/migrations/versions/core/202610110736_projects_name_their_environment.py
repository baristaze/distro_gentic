"""A project may name the environment its sessions' workspaces start from.

Revision ID: 202610110736
Revises: 202610110551
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610110736"
down_revision = "202610110551"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610110736_projects_name_their_environment.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610110736_projects_name_their_environment.down.sql")
