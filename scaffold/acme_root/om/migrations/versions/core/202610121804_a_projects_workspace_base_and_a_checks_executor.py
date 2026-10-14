"""A project names its workspace base, the engine's word for what it
builds, and a declared check names the executor that runs it: the column
and the key take the names, and every value stays.

Revision ID: 202610121804
Revises: 202610121803
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121804"
down_revision = "202610121803"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(
        DatabaseRole.CORE, "202610121804_a_projects_workspace_base_and_a_checks_executor.up.sql"
    )


def downgrade() -> None:
    run_sql(
        DatabaseRole.CORE, "202610121804_a_projects_workspace_base_and_a_checks_executor.down.sql"
    )
