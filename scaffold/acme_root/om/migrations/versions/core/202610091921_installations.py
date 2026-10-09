"""The installations a tenant connects, each naming one tenant across every
tenant, and when a person read a notification.

Revision ID: 202610091921
Revises: 202610091920
"""

from acme.om.storage.migrate import run_sql
from acme.om.storage.roles import DatabaseRole

revision = "202610091921"
down_revision = "202610091920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091921_installations.up.sql")


def downgrade() -> None:
    run_sql(DatabaseRole.CORE, "202610091921_installations.down.sql")
