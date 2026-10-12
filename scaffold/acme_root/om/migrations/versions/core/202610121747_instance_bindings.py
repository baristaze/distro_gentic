"""A workspace binding may hold an instance a run made for a session under
an id of its own, and names that session.

Revision ID: 202610121747
Revises: 202610121746
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610121747"
down_revision = "202610121746"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121747_instance_bindings.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610121747_instance_bindings.down.sql")
