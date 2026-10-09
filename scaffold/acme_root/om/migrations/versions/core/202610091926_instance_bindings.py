"""A workspace binding may hold an instance a run made for a session under
an id of its own, and names that session.

Revision ID: 202610091926
Revises: 202610091925
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091926"
down_revision = "202610091925"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091926_instance_bindings.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091926_instance_bindings.down.sql")
